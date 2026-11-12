"""Re-enter pending first-run credentials without resetting an existing account."""
import errno
import getpass
import json
import os
from pathlib import Path
import shutil
import tempfile
import urllib.error
import urllib.request

if __package__:
    from .website_config import read_settings,save_settings,validate
else:
    from website_config import read_settings,save_settings,validate


def check_uninitialized(root,opener=None):
    if (root/'.local/metabase-admin.json').exists():
        raise RuntimeError('A saved dashboard login already exists. No settings changed; use account recovery instead.')
    opener=opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open('http://127.0.0.1:3000/api/session/properties',timeout=3) as response:
            data=json.load(response)
    except urllib.error.HTTPError:
        raise RuntimeError('Cannot verify the local dashboard setup state. No settings changed.') from None
    except urllib.error.URLError as error:
        if isinstance(error.reason,OSError) and error.reason.errno==errno.ECONNREFUSED:
            return
        raise RuntimeError('Cannot verify the local dashboard setup state. No settings changed.') from None
    if not isinstance(data,dict) or not data.get('setup-token'):
        raise RuntimeError('The local dashboard is already configured or cannot be identified. No settings changed; use account recovery instead.')


def write_pending(root,email,password):
    if (root/'.local/metabase-admin.json').exists():
        raise RuntimeError('A saved dashboard login already exists. No settings changed.')
    if len(password)<14 or not all((any(c.isupper() for c in password),any(c.islower() for c in password),any(c.isdigit() for c in password))):
        raise ValueError('Choose a password with at least 14 characters, uppercase, lowercase and a number.')
    website=root/'.env.website'
    settings=read_settings(website) if website.exists() else {
        'DASHBOARD_DOMAIN':'finance.stockpkg.click','DASHBOARD_HTTPS_PORT':'8443'}
    settings['ACME_EMAIL']=email
    settings=validate(settings)
    local=root/'.local';local.mkdir(mode=0o700,exist_ok=True)
    pending=local/'requested-owner.json'
    backup=Path(tempfile.mkdtemp(prefix='login-backup-',dir=local))
    for source in (website,pending):
        if source.exists():
            target=backup/source.name
            shutil.copyfile(source,target);target.chmod(0o600)
    # Replace only pending input; databases, volumes and saved accounts are untouched.
    fd,name=tempfile.mkstemp(prefix='.requested-owner-',dir=local)
    try:
        with os.fdopen(fd,'w') as out: json.dump({'email':email,'password':password},out)
        save_settings(website,settings)
        os.replace(name,pending)
    finally:
        if os.path.exists(name): os.unlink(name)
    return backup


def main():
    root=Path(__file__).resolve().parent.parent
    check_uninitialized(root)
    while True:
        email=input('Enter the correct dashboard email: ').strip()
        try:
            validate({'DASHBOARD_DOMAIN':'finance.stockpkg.click','ACME_EMAIL':email})
        except ValueError:
            print('Please enter a complete email address.');continue
        break
    while True:
        password=getpass.getpass('Choose the dashboard password (14+ characters, uppercase, lowercase and a number): ')
        if len(password)<14 or not any(c.isupper() for c in password) or not any(c.islower() for c in password) or not any(c.isdigit() for c in password):
            print('Please choose a stronger password.');continue
        if password!=getpass.getpass('Confirm dashboard password: '):
            print('Passwords did not match.');continue
        break
    check_uninitialized(root)
    backup=write_pending(root,email,password)
    print('Pending login updated. Your password is not printed.')
    print('Previous pending settings were backed up privately to',backup.relative_to(root))


if __name__=='__main__':
    try: main()
    except (RuntimeError,ValueError,OSError) as error: raise SystemExit(str(error))
    except (KeyboardInterrupt,EOFError): raise SystemExit('Cancelled before saving the new login.')
