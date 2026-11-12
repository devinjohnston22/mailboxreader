"""First-run local Metabase setup. Credentials stay in a private ignored file."""
import json
import os
from pathlib import Path
import secrets
import time
import httpx
from provision_metabase import provision


def bootstrap():
    code_root=Path(__file__).resolve().parent.parent
    root=Path(os.getenv('MAILBOX_CONFIG_ROOT',str(code_root)))
    values={}
    for line in (root/'.env').read_text().splitlines():
        if line and not line.startswith('#') and '=' in line:
            name,value=line.split('=',1);values[name]=value
    access=root/'.local/metabase-admin.json'
    access.parent.mkdir(mode=0o700,exist_ok=True)
    with httpx.Client(base_url=os.getenv('METABASE_BOOTSTRAP_URL','http://127.0.0.1:3000'),trust_env=False,timeout=90) as client:
        for attempt in range(60):
            try:
                response=client.get('/api/health')
                if response.status_code==200: break
            except httpx.TransportError: pass
            time.sleep(2)
        else: raise RuntimeError('Metabase did not become ready')
        response=client.get('/api/session/properties');response.raise_for_status()
        setup=response.json().get('setup-token')
        if setup:
            if access.exists():
                raise RuntimeError('Metabase is fresh but saved admin credentials exist; preserve/review that file before a fresh setup')
            credentials={'email':'owner@localhost.invalid','password':secrets.token_urlsafe(40)}
            # Save before the request so a dropped response never loses the generated login.
            fd=os.open(access,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as f: json.dump(credentials,f)
            response=client.post('/api/setup',json={'token':setup,
                'user':dict(credentials,first_name='Mailbox',last_name='Owner'),
                'prefs':{'site_name':'Mailbox Reader','allow_tracking':False},
                'database':{'name':'Mailbox Reader (read only)','engine':'postgres','details':{
                    'host':'postgres','port':5432,'dbname':'mailbox','user':'mailbox_analytics',
                    'password':values['ANALYTICS_PASSWORD'],'ssl':False}}})
            response.raise_for_status()
        elif not access.exists():
            raise RuntimeError('Metabase is already configured; use scripts/provision_metabase.py with your API key')
        credentials=json.loads(access.read_text())
        response=client.post('/api/session',json={'username':credentials['email'],'password':credentials['password']});response.raise_for_status()
        client.headers['X-Metabase-Session']=response.json()['id']
        response=client.get('/api/database');response.raise_for_status()
        databases=response.json()['data']
        database=next((db for db in databases if db['name']=='Mailbox Reader (read only)'),None)
        if not database:
            response=client.post('/api/database',json={'name':'Mailbox Reader (read only)','engine':'postgres','details':{
                'host':'postgres','port':5432,'dbname':'mailbox','user':'mailbox_analytics',
                'password':values['ANALYTICS_PASSWORD'],'ssl':False},'is_full_sync':True})
            response.raise_for_status();database=response.json()
        dashboard=provision(client,database['id'])
        # Execute every saved card against the actual restricted PostgreSQL login.
        specs=json.loads((code_root/'dashboards/cards.json').read_text())
        for spec in specs:
            response=client.post('/api/dataset',json={'database':database['id'],'type':'native','native':{'query':spec['sql'],'template-tags':{}}})
            response.raise_for_status()
            if response.json().get('status')!='completed':
                raise RuntimeError('Dashboard SQL failed: '+spec['name'])
    print('Metabase dashboard provisioned and all eight queries executed. Dashboard ID:',dashboard)
    print('Local owner login saved privately to .local/metabase-admin.json. No public sharing enabled.')


if __name__=='__main__': bootstrap()
