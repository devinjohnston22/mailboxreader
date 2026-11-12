import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from psycopg.types.json import Jsonb
from .db import connect
from .domain import graph_url, initial_url, month_end, normalize_message, utc


class Conflict(Exception):
    pass


def claim(settings, stream):
    now = datetime.now(timezone.utc)
    with connect(settings) as db:
        if stream == 'history':
            if not settings.history_end:
                raise ValueError('Set a fixed HISTORY_END before enabling historical scan')
            start, end = utc(settings.history_start), utc(settings.history_end)
            if start >= end or end > now:
                raise ValueError('Historical bounds must satisfy start < end <= now')
            window_end = month_end(start,end)
        else:
            start = end = window_end = None
        db.execute('INSERT INTO sync_state(mailbox_id,stream,window_start,window_end,final_end) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                   (settings.mailbox_id,stream,start,window_end,end))
        row = db.execute('SELECT * FROM sync_state WHERE mailbox_id=%s AND stream=%s FOR UPDATE', (settings.mailbox_id,stream)).fetchone()
        if row['completed'] or (row['lease_until'] and row['lease_until'] > now) or (row['retry_at'] and row['retry_at'] > now):
            return {'ready':False, 'completed':row['completed']}
        url = graph_url(row['cursor_url'] or initial_url(stream,settings.live_folder,row['window_start'],row['window_end']))
        lease = uuid.uuid4()
        db.execute('UPDATE sync_state SET lease=%s,lease_until=%s,cursor_url=%s WHERE mailbox_id=%s AND stream=%s',
                   (lease,now+timedelta(minutes=10),url,settings.mailbox_id,stream))
        return {'ready':True,'lease':str(lease),'url':url}


def ingest_message(db, settings, raw):
    provider = raw.get('id')
    if not provider:
        raise ValueError('Missing Graph message ID')
    db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (settings.mailbox_id,))
    if '@removed' in raw:
        # A delta removal can mean a folder move, so preserve evidence but flag unavailable.
        db.execute('UPDATE messages SET deleted=true WHERE id IN (SELECT message_id FROM message_aliases WHERE mailbox_id=%s AND provider_id=%s)', (settings.mailbox_id,provider))
        return
    m = normalize_message(raw)
    link = urlsplit(m['web_link'])
    if link.scheme != 'https' or link.netloc not in ('outlook.office.com','outlook.office365.com','outlook.live.com'):
        m['web_link'] = ''
    # Serialize per mailbox. Live/history can overlap without alias/content races.
    alias = db.execute('SELECT message_id FROM message_aliases WHERE mailbox_id=%s AND provider_id=%s', (settings.mailbox_id,provider)).fetchone()
    if alias:
        existing = db.execute('SELECT canonical_key FROM messages WHERE id=%s', (alias['message_id'],)).fetchone()
        m['canonical_key'] = existing['canonical_key']
    row = db.execute('''INSERT INTO messages(mailbox_id,canonical_key,sender,subject,received_at,modified_at,content_hash,web_link)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(mailbox_id,canonical_key) DO UPDATE SET
        sender=EXCLUDED.sender,subject=EXCLUDED.subject,modified_at=EXCLUDED.modified_at,
        content_hash=EXCLUDED.content_hash,web_link=EXCLUDED.web_link,deleted=false
        WHERE messages.modified_at<=EXCLUDED.modified_at RETURNING id''',
        (settings.mailbox_id,m['canonical_key'],m['sender'],m['subject'],m['received_at'],m['modified_at'],m['content_hash'],m['web_link'])).fetchone()
    if not row:
        row = db.execute('SELECT id FROM messages WHERE mailbox_id=%s AND canonical_key=%s', (settings.mailbox_id,m['canonical_key'])).fetchone()
    db.execute('INSERT INTO message_aliases(mailbox_id,provider_id,message_id) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING', (settings.mailbox_id,provider,row['id']))
    db.execute('INSERT INTO source_versions(message_id,content_hash,source) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING', (row['id'],m['content_hash'],m['source']))


def commit_page(settings, stream, lease, status, body, headers):
    now = datetime.now(timezone.utc)
    with connect(settings) as db:
        row = db.execute('SELECT * FROM sync_state WHERE mailbox_id=%s AND stream=%s FOR UPDATE', (settings.mailbox_id,stream)).fetchone()
        if not row or str(row['lease']) != lease or row['lease_until'] < now:
            raise Conflict('Expired or stale page lease; page was not committed')
        if status != 200:
            error = 'graph_' + str(status)
            retry = 60
            try:
                retry = max(30,min(86400,int({k.lower():v for k,v in headers.items()}.get('retry-after',60))))
            except (TypeError,ValueError):
                pass
            # Expired delta tokens restart a read-only baseline, deduplicated normally.
            reset = status == 410 and stream == 'live'
            db.execute('''UPDATE sync_state SET lease=NULL,lease_until=NULL,retry_at=%s,last_error=%s,
                cursor_url=CASE WHEN %s THEN NULL ELSE cursor_url END,updated_at=now()
                WHERE mailbox_id=%s AND stream=%s''', (now+timedelta(seconds=retry),error,reset,settings.mailbox_id,stream))
            return {'committed':False,'error':error,'retry_seconds':retry,'oauth_required':status in (401,403)}
        if not isinstance(body,dict) or not isinstance(body.get('value'),list) or len(body['value']) > 1000:
            raise ValueError('Invalid Graph page')
        next_url = body.get('@odata.nextLink')
        delta = body.get('@odata.deltaLink')
        if next_url and delta:
            raise ValueError('Ambiguous Graph cursors')
        if next_url or delta:
            graph_url(next_url or delta)
        if stream == 'live' and not (next_url or delta):
            raise ValueError('Live delta response omitted checkpoint')
        for raw in body['value']:
            ingest_message(db,settings,raw)
        start, end, complete = row['window_start'],row['window_end'],False
        if stream == 'history' and not next_url:
            if end >= row['final_end']:
                complete = True
            else:
                start, end = end,month_end(end,row['final_end'])
        cursor = next_url or (delta if stream == 'live' else None)
        db.execute('''UPDATE sync_state SET cursor_url=%s,window_start=%s,window_end=%s,completed=%s,
            pages=pages+1,lease=NULL,lease_until=NULL,retry_at=NULL,last_error=NULL,updated_at=now()
            WHERE mailbox_id=%s AND stream=%s''', (cursor,start,end,complete,settings.mailbox_id,stream))
        db.execute('INSERT INTO audit_log(event,details) VALUES(%s,%s)', ('sync_page',Jsonb({'stream':stream,'count':len(body['value'])})))
        return {'committed':True,'count':len(body['value']),'completed':complete}
