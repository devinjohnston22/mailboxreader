"""Run prepared VPS setup in its own session and retain a private progress log."""
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

if __package__:
    from .website_config import read_settings,origin
else:
    from website_config import read_settings,origin


class SetupRunning(RuntimeError):
    pass


def active_setups(root,proc=Path('/proc')):
    scripts={'install_vps.sh','bootstrap_vps.sh','reenter_dashboard_login.py'}
    found=[]
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name)==os.getpid(): continue
        try:
            args=entry.joinpath('cmdline').read_bytes().split(b'\0')
            if len(args)<2: continue
            script=Path(os.fsdecode(args[1]))
            if script.name not in scripts: continue
            if script.is_absolute():
                matches=script.parent==root/'scripts'
            else:
                matches=entry.joinpath('cwd').resolve()==root and script.parent==Path('scripts')
            if matches: found.append(int(entry.name))
        except (OSError,ValueError): continue
    return found


def launch(root,proc=Path('/proc')):
    root=root.resolve()
    local=root/'.local';local.mkdir(mode=0o700,exist_ok=True)
    lock=os.open(local/'setup.lock',os.O_CREAT|os.O_RDWR,0o600)
    try:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise SetupRunning('A background installation is already running. Check .local/setup.log.') from None
        running=active_setups(root,proc)
        if running:
            raise SetupRunning('An existing setup is still running (PID '+', '.join(map(str,running))+'). Leave it running; the original console may be waiting for input.')
        settings=read_settings(root/'.env.website')
        account=next((local/name for name in ('metabase-admin.json','requested-owner.json') if (local/name).is_file()),None)
        if account is None:
            raise RuntimeError('Login details have not been saved. Run python3 scripts/reenter_dashboard_login.py first.')
        try:
            data=json.loads(account.read_text())
            valid=isinstance(data,dict) and isinstance(data.get('email'),str) and isinstance(data.get('password'),str) and len(data['password'])>=14
        except (OSError,ValueError): valid=False
        if not valid: raise RuntimeError('Stored login settings need review. No installation started.')
        log=os.open(local/'setup.log',os.O_CREAT|os.O_WRONLY|os.O_APPEND,0o600)
        try:
            os.fchmod(log,0o600)
            os.write(log,('\n=== Setup started '+time.strftime('%Y-%m-%d %H:%M:%S UTC',time.gmtime())+' ===\n').encode())
            (local/'setup-status.json').unlink(missing_ok=True)
            child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--worker',str(root)],
                cwd=root,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
                start_new_session=True,pass_fds=(lock,))
            fd=os.open(local/'setup.pid',os.O_CREAT|os.O_WRONLY|os.O_TRUNC,0o600)
            with os.fdopen(fd,'w') as out: out.write(str(child.pid)+'\n')
            return child
        finally: os.close(log)
    finally: os.close(lock)


def worker(root):
    code=1
    try:
        settings=read_settings(root/'.env.website')
        env=dict(os.environ,DASHBOARD_HTTPS_PORT=settings['DASHBOARD_HTTPS_PORT'],PYTHONUNBUFFERED='1')
        # Pause only this project's website during private initialization. Its
        # databases/volumes and other services on the server remain in place.
        if (root/'.env').exists() and shutil.which('docker'):
            command=['docker','compose','--env-file','.env','--env-file','.env.website','-f','compose.yaml']
            if os.getenv('CODEX_PROXY_CERT'): command+=['-f','compose.cloud.yaml']
            command+=['-f','compose.website.yaml','--profile','website','stop','website']
            subprocess.run(command,cwd=root,env=env,check=True)
        code=subprocess.run(['bash','scripts/install_vps.sh'],cwd=root,env=env).returncode
    except Exception as error:
        print('Setup stopped:',type(error).__name__,flush=True)
    finally:
        status={'exit_code':code,'finished_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
        fd,name=tempfile.mkstemp(prefix='.setup-status-',dir=root/'.local')
        with os.fdopen(fd,'w') as out: json.dump(status,out)
        os.replace(name,root/'.local/setup-status.json')
        print('Setup completed.' if code==0 else 'Setup stopped. Review the preceding error in .local/setup.log.',flush=True)
    return code


def main():
    if len(sys.argv)==3 and sys.argv[1]=='--worker':
        return worker(Path(sys.argv[2]))
    if os.geteuid()!=0: raise RuntimeError('Run this command as root in the VPS console.')
    root=Path(__file__).resolve().parent.parent
    child=launch(root)
    print('Installation started in background. PID:',child.pid)
    print('It continues if the browser console disconnects.')
    print('To view progress: tail -n 25 /opt/mailboxreader/.local/setup.log')
    print('Website address after successful HTTPS verification:',origin(read_settings(root/'.env.website')))
    return 0


if __name__=='__main__':
    try: raise SystemExit(main())
    except SetupRunning as error: print(str(error))
    except (RuntimeError,ValueError,OSError) as error: raise SystemExit(str(error))
