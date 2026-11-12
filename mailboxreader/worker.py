import uuid
from datetime import datetime, timedelta, timezone
from psycopg.types.json import Jsonb
from .ai import extract
from .db import connect
from .domain import digest, transaction_key, grounded
from .sync import Conflict


def save_extraction(db, settings, job, result):
    grounded(result,job['source'])
    current = db.execute('SELECT lease FROM source_versions WHERE id=%s FOR UPDATE', (job['id'],)).fetchone()
    if str(current['lease']) != str(job['lease']):
        raise Conflict('Extraction lease superseded')
    domain = job['sender'].rsplit('@',1)[-1] if '@' in job['sender'] else ''
    for category, items in [('transaction',result.transactions),('payment_method',result.payment_methods),('contact',result.contacts)]:
        for item in items:
            payload = item.model_dump(mode='json',exclude={'quote'})
            fingerprint = digest(item.model_dump_json())
            key = transaction_key(settings.mailbox_id,job['canonical_key'],domain,item) if category == 'transaction' else None
            db.execute('''INSERT INTO facts(version_id,category,fingerprint,transaction_key,vendor_domain,payload,quote)
                VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
                (job['id'],category,fingerprint,key,domain,Jsonb(payload),item.quote))
    db.execute("UPDATE source_versions SET status='done',model=%s,processed_at=now(),lease=NULL,lease_until=NULL,error_code=NULL WHERE id=%s", (settings.ai_model,job['id']))
    db.execute('INSERT INTO audit_log(event,details) VALUES(%s,%s)', ('extraction_complete',Jsonb({'version_id':job['id'],'facts':len(result.transactions)+len(result.contacts)+len(result.payment_methods)})))


def run_one(settings, extractor=extract):
    if not settings.ai_enabled:
        return {'processed':False,'reason':'ai_disabled'}
    if not settings.ai_api_key:
        return {'processed':False,'reason':'ai_key_missing'}
    now, lease = datetime.now(timezone.utc),uuid.uuid4()
    with connect(settings) as db:
        db.execute("""UPDATE source_versions v SET status='failed',error_code='LeaseExpired',lease=NULL,lease_until=NULL
            FROM messages m WHERE m.id=v.message_id AND m.mailbox_id=%s AND v.status='processing'
            AND v.lease_until<now() AND v.attempts>=5""", (settings.mailbox_id,))
        job = db.execute('''SELECT v.*,m.sender,m.canonical_key FROM source_versions v
            JOIN messages m ON m.id=v.message_id WHERE NOT m.deleted AND m.mailbox_id=%s
            AND v.content_hash=m.content_hash AND v.attempts<5
            AND (v.status IN ('pending','failed') OR (v.status='processing' AND v.lease_until<now()))
            AND (v.retry_at IS NULL OR v.retry_at<=now()) ORDER BY v.id FOR UPDATE OF v SKIP LOCKED LIMIT 1''', (settings.mailbox_id,)).fetchone()
        if not job:
            return {'processed':False,'reason':'queue_empty'}
        db.execute("UPDATE source_versions SET status='processing',lease=%s,lease_until=%s,attempts=attempts+1 WHERE id=%s", (lease,now+timedelta(minutes=3),job['id']))
        job['lease'] = lease
    try:
        result = extractor(job['source'],settings)
        with connect(settings) as db:
            save_extraction(db,settings,job,result)
        return {'processed':True,'version_id':job['id']}
    except Exception as error:
        # Do not persist provider error messages or model output containing email data.
        code = type(error).__name__
        with connect(settings) as db:
            db.execute("UPDATE source_versions SET status='failed',error_code=%s,retry_at=%s,lease=NULL,lease_until=NULL WHERE id=%s AND lease=%s",
                       (code,now+timedelta(seconds=min(3600,60*2**job['attempts'])),job['id'],lease))
        return {'processed':False,'version_id':job['id'],'error_code':code}
