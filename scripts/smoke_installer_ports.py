"""Exercise the real installer preflight in an isolated container with busy ports.

Build mailboxreader-api:local first. No packages, network services, credentials,
or host firewall settings are changed by these tests.
"""
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    root=Path(__file__).resolve().parent.parent
    env={k:v for k,v in os.environ.items() if k not in ('DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH')}
    code='''import os,socket,subprocess
busy443=socket.socket();busy443.bind(('0.0.0.0',443));busy443.listen()
def check(port,success):
 env=dict(os.environ,DASHBOARD_HTTPS_PORT=str(port))
 result=subprocess.run(['bash','scripts/install_vps.sh','--check-only'],env=env,text=True,capture_output=True)
 assert (result.returncode==0)==success,(port,result.stdout,result.stderr)
 assert busy443.getsockname()[1]==443
 if success: assert 'HTTPS 8443' in result.stdout
 else: assert 'Port '+str(port)+' is unavailable' in result.stderr
check(8443,True)
check(443,False)
busy8443=socket.socket();busy8443.bind(('0.0.0.0',8443));busy8443.listen()
check(8443,False)
assert busy8443.getsockname()[1]==8443
print('Installer preflight passed: occupied 443 preserved; free 8443 accepted; occupied 8443 rejected.')
'''
    with tempfile.TemporaryDirectory(dir=root/'.local') as folder:
        fixture=Path(folder)/'os-release'
        fixture.write_text('ID=ubuntu\nVERSION_ID="26.04"\n')
        fixture.chmod(0o644)
        args=['docker','--host=unix:///var/run/docker.sock','run','--rm','--network','none','--user','0',
              '--mount',f'type=bind,src={fixture},dst=/etc/os-release,readonly',
              '--entrypoint','python','mailboxreader-api:local','-c',code]
        subprocess.run(args,env=env,check=True)


if __name__=='__main__': main()
