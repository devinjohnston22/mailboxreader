"""Runs only against an explicitly supplied disposable PostgreSQL database."""
import os
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from psycopg.errors import InsufficientPrivilege
import psycopg
from mailboxreader.api import create_app
from mailboxreader.config import Settings
from mailboxreader.db import connect, migrate
from mailboxreader.domain import normalize_message
from mailboxreader.sync import claim, commit_page, Conflict
from mailboxreader.worker import run_one
from scripts.create_analytics_role import provision
from test_domain import SOURCE, message, result


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'),'TEST_DATABASE_URL not set: disposable PostgreSQL required')
class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings=Settings(os.environ['TEST_DATABASE_URL'],'test-token-'+'x'*40,
            history_start='2019-12-01T00:00:00Z',history_end='2020-02-01T00:00:00Z',ai_enabled=True,ai_api_key='synthetic')
        migrate(cls.settings)
        migrate(cls.settings)  # checks idempotence and migration checksum verification

    def setUp(self):
        with connect(self.settings) as db:
            db.execute('TRUNCATE sync_state,messages,monitor_settings,reviews,audit_log RESTART IDENTITY CASCADE')
            db.execute('INSERT INTO monitor_settings VALUES(%s,10000,\'USD\')',(self.settings.mailbox_id,))

    def ingest(self,items,stream='live',status=200,headers=None):
        page=claim(self.settings,stream)
        self.assertTrue(page['ready'])
        return commit_page(self.settings,stream,page['lease'],status,{'value':items,'@odata.deltaLink':'https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?$deltatoken=test'} if stream=='live' else {'value':items},headers or {})

    def count(self,table):
        # Table names originate only from this test module.
        with connect(self.settings) as db: return db.execute('SELECT count(*) AS n FROM '+table).fetchone()['n']

    def test_live_history_overlap_and_fact_dedup(self):
        self.ingest([message()]);self.ingest([message(id='copy')],'history');self.ingest([message()])
        self.assertEqual(self.count('messages'),1)
        self.assertEqual(self.count('source_versions'),1)
        self.assertEqual(self.count('message_aliases'),2)
        self.assertTrue(run_one(self.settings,lambda *_:result())['processed'])
        self.assertEqual(self.count('facts'),3)
        self.assertEqual(self.count('possible_overdue'),1)
        self.assertEqual(self.count('vendor_payment_methods'),1)
        self.assertEqual(self.count('finance_contacts'),1)
        self.assertEqual(run_one(self.settings,lambda *_:result())['reason'],'queue_empty')

    def test_atomic_rollback_and_fenced_leases(self):
        page=claim(self.settings,'live')
        self.assertFalse(claim(self.settings,'live')['ready'])
        with self.assertRaises(ValueError):
            commit_page(self.settings,'live',page['lease'],200,{'value':[message(),{'id':'bad'}],'@odata.deltaLink':'https://graph.microsoft.com/v1.0/me/messages/delta'}, {})
        self.assertEqual(self.count('messages'),0)
        with connect(self.settings) as db: db.execute("UPDATE sync_state SET lease_until=now()-interval '1 minute'")
        new=claim(self.settings,'live')
        with self.assertRaises(Conflict): commit_page(self.settings,'live',page['lease'],200,{'value':[]},{})
        commit_page(self.settings,'live',new['lease'],200,{'value':[],'@odata.deltaLink':'https://graph.microsoft.com/v1.0/me/messages/delta'}, {})

    def test_429_and_delta_expiry(self):
        reply=self.ingest([],status=429,headers={'Retry-After':'180'})
        self.assertEqual(reply['retry_seconds'],180)
        self.assertFalse(claim(self.settings,'live')['ready'])
        with connect(self.settings) as db: db.execute('UPDATE sync_state SET retry_at=NULL')
        self.ingest([],status=410)
        with connect(self.settings) as db:
            self.assertIsNone(db.execute('SELECT cursor_url FROM sync_state').fetchone()['cursor_url'])

    def test_backfill_window_progress_and_completion(self):
        self.ingest([],'history')
        with connect(self.settings) as db:
            row=db.execute("SELECT * FROM sync_state WHERE stream='history'").fetchone()
            self.assertEqual(row['window_start'].month,1)
        self.assertTrue(self.ingest([],'history')['completed'])
        self.assertFalse(claim(self.settings,'history')['ready'])

    def test_updates_and_deletions_hide_stale_facts(self):
        self.ingest([message()]);run_one(self.settings,lambda *_:result())
        newer=message(text='Updated: no financial information')
        newer['lastModifiedDateTime']='2020-01-02T00:00:00Z'
        self.ingest([newer])
        self.assertEqual(self.count('possible_overdue'),0)
        self.assertEqual(self.count('source_versions'),2)
        self.ingest([message()])  # stale history must not overwrite a newer version
        self.assertEqual(self.count('possible_overdue'),0)
        self.ingest([{'id':'msg-1','@removed':{'reason':'deleted'}}])
        self.assertEqual(self.count('transaction_candidates'),0)

    def test_failed_ai_not_accepted_and_bounded_retry(self):
        self.ingest([message()])
        def fail(*args): raise ValueError('sensitive content must not be logged')
        response=run_one(self.settings,fail)
        self.assertEqual(response['error_code'],'ValueError')
        self.assertEqual(self.count('facts'),0)
        self.assertEqual(run_one(self.settings,fail)['reason'],'queue_empty')

    def test_monitor_requires_currency_direction_due_date_and_threshold(self):
        self.ingest([message()]);run_one(self.settings,lambda *_:result())
        self.assertEqual(self.count('possible_overdue'),1)
        for field,value in [('currency','EUR'),('direction','unknown'),('due_date',None),('amount','9999')]:
            with self.subTest(field=field):
                with connect(self.settings) as db:
                    db.execute("UPDATE facts SET payload=jsonb_set(payload,%s,%s::jsonb) WHERE category='transaction'", ('{'+field+'}',__import__('json').dumps(value)))
                self.assertEqual(self.count('possible_overdue'),0)
                with connect(self.settings) as db:
                    from psycopg.types.json import Jsonb
                    db.execute("UPDATE facts SET payload=%s WHERE category='transaction'", (Jsonb(result().transactions[0].model_dump(mode='json',exclude={'quote'})),))

    def test_invalid_ai_does_not_store_partial_facts(self):
        self.ingest([message()])
        data=result();data.transactions[0].reference='FABRICATED'
        response=run_one(self.settings,lambda *_:data)
        self.assertEqual(response['error_code'],'ValueError')
        self.assertEqual(self.count('facts'),0)

    def test_final_expired_extraction_attempt_becomes_visible_failure(self):
        self.ingest([message()])
        with connect(self.settings) as db:
            db.execute("UPDATE source_versions SET status='processing',attempts=5,lease_until=now()-interval '1 minute'")
        self.assertEqual(run_one(self.settings,lambda *_:result())['reason'],'queue_empty')
        with connect(self.settings) as db:
            row=db.execute('SELECT status,error_code FROM source_versions').fetchone()
            self.assertEqual(row,{'status':'failed','error_code':'LeaseExpired'})

    def test_api_auth_review_and_evidence(self):
        self.ingest([message()]);run_one(self.settings,lambda *_:result())
        with TestClient(create_app(self.settings)) as client:
            self.assertEqual(client.get('/monitor').status_code,401)
            headers={'Authorization':'Bearer '+self.settings.api_token}
            response=client.get('/monitor',headers=headers)
            self.assertEqual(response.status_code,200)
            findings=response.json()['findings'];self.assertEqual(len(findings),1)
            response=client.post('/review/'+findings[0]['transaction_key'],headers=headers,json={'status':'paid','note':'Confirmed by human reviewer'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(client.get('/monitor',headers=headers).json()['findings'],[])
            self.assertEqual(client.get('/evidence/1',headers=headers).status_code,200)
            response=client.post('/sync/live/page',headers=headers,json={'secret':'do-not-echo'})
            self.assertEqual(response.status_code,422)
            self.assertNotIn('do-not-echo',response.text)

    def test_analytics_role_cannot_read_raw_sources_or_write(self):
        from psycopg.conninfo import conninfo_to_dict
        with psycopg.connect(self.settings.database_url) as db: provision(db,'synthetic-analytics-password-'+'x'*32)
        args=conninfo_to_dict(self.settings.database_url)
        args.update(user='mailbox_analytics',password='synthetic-analytics-password-'+'x'*32)
        with psycopg.connect(**args,autocommit=True) as db:
            db.execute('SELECT * FROM mailbox.possible_overdue')
            with self.assertRaises(InsufficientPrivilege): db.execute('SELECT source FROM mailbox.source_versions')
            # Override read-only transaction default to demonstrate actual GRANT restrictions.
            db.execute('SET default_transaction_read_only=off')
            with self.assertRaises(InsufficientPrivilege): db.execute('DELETE FROM mailbox.messages')


if __name__=='__main__': unittest.main()
