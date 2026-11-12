"""Exercise real n8n nodes against a synthetic Graph server and isolated mailbox alias.

Requires the local Compose stack. No Microsoft credentials or external AI are used.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN='synthetic-smoke-token-not-a-production-credential'
ALIAS='synthetic-runtime-smoke'


def serve():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body={'value':[{'id':'synthetic-runtime-1','internetMessageId':'<synthetic-runtime@example.invalid>',
                'subject':'Synthetic smoke test','from':{'emailAddress':{'address':'billing@example.invalid'}},
                'body':{'contentType':'text','content':'Synthetic data only. No real financial information.'},
                'receivedDateTime':'2020-01-01T00:00:00Z','lastModifiedDateTime':'2020-01-01T00:00:00Z'}]}
            if 'stream=live' in self.path:
                body['@odata.deltaLink']='https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?$deltatoken=synthetic'
            data=json.dumps(body).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(data)
        def log_message(self,*args): pass
    HTTPServer(('0.0.0.0',8010),Handler).serve_forever()


def main():
    root=Path(__file__).resolve().parent.parent
    os.chdir(root)
    env={k:v for k,v in os.environ.items() if k not in ('DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH')}
    base=['docker','--host=unix:///var/run/docker.sock','compose','-f','compose.yaml']
    if os.getenv('CODEX_PROXY_CERT'): base+=['-f','compose.cloud.yaml']
    def run(*args,check=True):
        result=subprocess.run(base+list(args),env=env,capture_output=True,text=True)
        if check and result.returncode:
            raise RuntimeError('Synthetic runtime check failed: '+result.stdout[-4000:]+result.stderr[-2000:])
        return result
    local=root/'.local';local.mkdir(exist_ok=True,mode=0o700)
    try:
        run('exec','-d','api','sh','-c','echo $$ > /tmp/smoke-graph.pid; exec python scripts/smoke_stack.py --serve')
        run('exec','-d','-e','MAILBOX_ID='+ALIAS,'-e','API_TOKEN='+TOKEN,'-e','AI_ENABLED=false','api','sh','-c',
            'echo $$ > /tmp/smoke-api.pid; exec uvicorn mailboxreader.api:create_app --factory --host 0.0.0.0 --port 8001 --no-access-log')
        for attempt in range(30):
            ready=run('exec','-T','api','python','-c',"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health')",check=False)
            if ready.returncode==0: break
            time.sleep(1)
        else: raise RuntimeError('Synthetic API failed to start')
        for index,filename in enumerate(['outlook_live.json','outlook_history.json','extract_and_monitor.json']):
            data=json.loads((root/'workflows'/filename).read_text())
            data['id']='SyntheticSmoke00'+str(index)
            data['name']='SYNTHETIC ONLY '+filename
            for node in data['nodes']:
                if node['type']=='n8n-nodes-base.scheduleTrigger':
                    node['type']='n8n-nodes-base.manualTrigger';node['typeVersion']=1;node['parameters']={}
                if node['type']=='n8n-nodes-base.httpRequest':
                    p=node['parameters'];node.pop('credentials',None);p['authentication']='none';p.pop('genericAuthType',None)
                    if node['name']=='Read Outlook page':
                        stream='live' if index==0 else 'history'
                        p['url']='http://api:8010/graph?stream='+stream
                    else:
                        p['url']=p['url'].replace('http://api:8000','http://api:8001')
                        p['sendHeaders']=True;p['headerParameters']={'parameters':[{'name':'Authorization','value':'Bearer '+TOKEN}]}
            temp=local/'smoke-workflow.json';temp.write_text(json.dumps(data));temp.chmod(0o600)
            run('cp',str(temp),'n8n:/tmp/smoke-workflow.json')
            run('exec','-T','n8n','n8n','import:workflow','--input=/tmp/smoke-workflow.json')
            executed=run('exec','-T','-e','N8N_RUNNERS_BROKER_PORT=5689','n8n','n8n','execute','--id='+data['id'])
            if 'Workflow execution finished successfully' not in executed.stdout and '"finished": true' not in executed.stdout:
                raise RuntimeError('n8n did not report successful completion: '+executed.stdout[-2000:])
            print('Executed synthetic workflow:',filename)
        assertion=f"""from mailboxreader.config import Settings
from mailboxreader.db import connect
with connect(Settings.from_env()) as db:
 assert db.execute('SELECT count(*) AS n FROM messages WHERE mailbox_id=%s',('{ALIAS}',)).fetchone()['n']==1
 assert db.execute('SELECT sum(pages) AS n FROM sync_state WHERE mailbox_id=%s',('{ALIAS}',)).fetchone()['n']==2
print('Synthetic n8n import/execute/checkpoint/dedup passed')
"""
        print(run('exec','-T','api','python','-c',assertion).stdout.strip())
    finally:
        cleanup=f"""from mailboxreader.config import Settings
from mailboxreader.db import connect
with connect(Settings.from_env()) as db:
 for table in ['messages','sync_state','monitor_settings']:
  db.execute('DELETE FROM '+table+' WHERE mailbox_id=%s',('{ALIAS}',))
"""
        run('exec','-T','api','python','-c',cleanup,check=False)
        run('exec','-T','api','sh','-c','for f in /tmp/smoke-api.pid /tmp/smoke-graph.pid; do if [ -f "$f" ]; then kill "$(cat "$f")"; rm -f "$f"; fi; done',check=False)
        run('exec','-T','n8n','rm','-f','/tmp/smoke-workflow.json',check=False)
        (local/'smoke-workflow.json').unlink(missing_ok=True)


if __name__=='__main__':
    serve() if '--serve' in sys.argv else main()
