"""Verify public HTTPS and GUI responses; never accept invalid certificates."""
import time
import httpx
if __package__:
    from .website_config import read_settings,origin
else:
    from website_config import read_settings,origin


def verify(settings,client=None):
    url=origin(settings)
    def check(c):
        response=c.get(url+'/api/health',timeout=20)
        response.raise_for_status()
        if response.json().get('status')!='ok':
            raise RuntimeError('Website database readiness check did not pass')
        response=c.get(url+'/',timeout=20)
        response.raise_for_status()
        if 'text/html' not in response.headers.get('content-type',''):
            raise RuntimeError('Website did not serve the dashboard GUI')
        if 'max-age=' not in response.headers.get('strict-transport-security',''):
            raise RuntimeError('HTTPS security headers are missing')
        return url
    if client is not None: return check(client)
    with httpx.Client(follow_redirects=False) as c: return check(c)


if __name__=='__main__':
    settings=read_settings('.env.website')
    for attempt in range(30):
        try:
            url=verify(settings)
            print('Verified HTTPS dashboard website:',url)
            print('Sign in with the private owner login in .local/metabase-admin.json.')
            break
        except (httpx.HTTPError,ValueError,RuntimeError):
            if attempt==29:
                raise SystemExit('Website verification failed. Check DNS, port 80 and your selected HTTPS port, Caddy certificate logs and host firewall; no public website readiness is claimed.')
            time.sleep(2)
