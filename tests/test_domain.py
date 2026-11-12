import json
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import httpx
from pydantic import ValidationError
from mailboxreader.ai import extract
from mailboxreader.config import Settings
from mailboxreader.domain import Extraction, grounded, graph_url, initial_url, month_end, normalize_message, transaction_key
from scripts.generate_workflows import generate

SOURCE = 'Acme invoice INV-42: USD 15000.00 due 2020-01-15. Pay by ACH. Finance: billing@acme.example.'


def result():
    return Extraction.model_validate({'transactions':[{'kind':'invoice','direction':'payable','vendor':'Acme','reference':'INV-42',
        'amount':'15000.00','currency':'USD','due_date':'2020-01-15','confidence':0.95,'quote':SOURCE}],
        'payment_methods':[{'vendor':'Acme','method':'ach','quote':SOURCE}],
        'contacts':[{'email':'billing@acme.example','name':'','role':'billing','quote':SOURCE}]})


def message(id='msg-1',internet_id='<inv42@acme.example>',text=SOURCE):
    return {'id':id,'internetMessageId':internet_id,'subject':'Acme invoice',
            'from':{'emailAddress':{'address':'billing@acme.example'}},
            'body':{'contentType':'text','content':text},'receivedDateTime':'2020-01-01T12:00:00Z',
            'lastModifiedDateTime':'2020-01-01T12:00:00Z','webLink':'https://outlook.office.com/mail/id/synthetic'}


class DomainTests(unittest.TestCase):
    def test_exact_evidence(self):
        self.assertEqual(grounded(result(),SOURCE).transactions[0].amount,Decimal('15000'))
        with self.assertRaises(ValueError): grounded(result(),'different email')

    def test_fabricated_fields_rejected(self):
        for field,value in [('amount','10'),('reference','FAKE'),('currency','EUR'),('vendor','Unknown'),('due_date','2025-02-15')]:
            with self.subTest(field=field):
                data=result().model_dump(mode='json')
                data['transactions'][0][field]=value
                with self.assertRaises(ValueError): grounded(Extraction.model_validate(data),SOURCE)

    def test_reject_unsupported_and_sensitive_output_fields(self):
        for field,value in [('amount','NaN'),('amount','-5'),('kind','send_payment'),('account_number','12345')]:
            data=result().model_dump(mode='json'); data['transactions'][0][field]=value
            with self.assertRaises(ValidationError): Extraction.model_validate(data)

    def test_fabricated_contact_role_and_payment_method_rejected(self):
        data=result().model_dump(mode='json');data['contacts'][0]['role']='accounts_payable'
        with self.assertRaises(ValueError): grounded(Extraction.model_validate(data),SOURCE)
        data=result().model_dump(mode='json');data['payment_methods'][0]['method']='paypal'
        with self.assertRaises(ValueError): grounded(Extraction.model_validate(data),SOURCE)

    def test_message_and_transaction_dedup(self):
        a,b=normalize_message(message()),normalize_message(message(id='immutable-copy'))
        self.assertEqual(a['canonical_key'],b['canonical_key'])
        invoice=result().transactions[0]
        key=lambda msg,domain,item: transaction_key('primary',msg,domain,item)
        self.assertEqual(key('m1','acme.example',invoice),key('m2','acme.example',invoice))
        self.assertNotEqual(key('m1','acme.example',invoice),key('m1','other.example',invoice))
        payment=invoice.model_copy(update={'kind':'payment'})
        self.assertNotEqual(key('m1','acme.example',payment),key('m2','acme.example',payment))

    def test_graph_url_ssrf_guard(self):
        for url in ['http://graph.microsoft.com/v1.0/me/messages','https://graph.microsoft.com.evil/v1.0/me/messages',
                    'https://graph.microsoft.com@evil/v1.0/me/messages','https://graph.microsoft.com:443/v1.0/me/messages',
                    'https://graph.microsoft.com/v1.0/users/other/messages','https://evil/me/messages']:
            with self.assertRaises(ValueError): graph_url(url)
        self.assertTrue(graph_url(initial_url('live','inbox')).startswith('https://graph.microsoft.com/'))

    def test_no_html_or_silent_truncation(self):
        m=message();m['body']['contentType']='html'
        with self.assertRaises(ValueError): normalize_message(m)
        with self.assertRaises(ValueError): normalize_message(message(text='x'*1_000_001))

    def test_historical_half_open_bounds(self):
        start=datetime(2020,12,1,tzinfo=timezone.utc);end=datetime(2021,1,15,tzinfo=timezone.utc)
        self.assertEqual(month_end(start,end),datetime(2021,1,1,tzinfo=timezone.utc))
        self.assertEqual(month_end(month_end(start,end),end),end)

    def test_ai_consent_gate_and_mock_provider(self):
        settings=Settings('unused','x'*40)
        with self.assertRaises(RuntimeError): extract(SOURCE,settings)
        def respond(request):
            self.assertEqual(request.url.host,'api.openai.com')
            payload=json.loads(request.content)
            self.assertFalse(payload['store'])
            self.assertNotIn('tools',payload)
            return httpx.Response(200,json={'choices':[{'message':{'content':result().model_dump_json()}}]})
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            actual=extract(SOURCE,replace(settings,ai_enabled=True,ai_api_key='synthetic'),client)
            self.assertEqual(actual,result())

    def test_workflows_reproducible_and_read_only(self):
        root=Path(__file__).resolve().parent.parent
        for name,workflow in generate().items():
            self.assertEqual(workflow,json.loads((root/'workflows'/name).read_text()))
            self.assertFalse(workflow['active'])
            self.assertEqual(workflow['settings']['saveDataSuccessExecution'],'none')
            names={node['name'] for node in workflow['nodes']}
            for source,edges in workflow['connections'].items():
                self.assertIn(source,names)
                for output in edges['main']:
                    for edge in output: self.assertIn(edge['node'],names)
            for node in workflow['nodes']:
                if node['name']=='Read Outlook page':
                    self.assertEqual(node['parameters']['method'],'GET')
                    self.assertFalse(node['parameters']['options']['redirect']['redirect']['followRedirects'])


if __name__=='__main__': unittest.main()
