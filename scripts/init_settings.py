"""Generate secure local settings; never overwrite an existing .env."""
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path


def initialize(root):
    target=root/'.env'
    content=(root/'.env.example').read_text()
    for name in ['POSTGRES_PASSWORD','DB_ADMIN_PASSWORD','API_TOKEN','N8N_ENCRYPTION_KEY','METABASE_DB_PASSWORD','ANALYTICS_PASSWORD']:
        content=content.replace(name+'=\n',name+'='+secrets.token_hex(32)+'\n')
    content=content.replace('HISTORY_END=\n','HISTORY_END='+datetime.now(timezone.utc).isoformat()+'\n')
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f: f.write(content)


if __name__=='__main__':
    initialize(Path(__file__).resolve().parent.parent)
    print('Created private .env with random credentials and a fixed historical boundary. No mailbox access enabled.')
