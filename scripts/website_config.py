"""Validate public website settings before opening internet-facing ports."""
import ipaddress
import re
from pathlib import Path


def read_settings(path):
    result={}
    for line in Path(path).read_text().splitlines():
        line=line.strip()
        if not line or line.startswith('#'): continue
        if '=' not in line: raise ValueError('Website settings must use NAME=value')
        name,value=line.split('=',1)
        if name not in ('DASHBOARD_DOMAIN','ACME_EMAIL'):
            raise ValueError('Unexpected website setting: '+name)
        if name in result: raise ValueError('Duplicate website setting: '+name)
        result[name]=value.strip()
    return validate(result)


def validate(settings):
    domain=settings.get('DASHBOARD_DOMAIN','')
    email=settings.get('ACME_EMAIL','')
    if (len(domain)>253 or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}',domain)
            or domain.endswith(('.localhost','.local','.invalid','.test','.example'))
            or domain in ('localhost','example.com','example.org','example.net')
            or domain.endswith(('.example.com','.example.org','.example.net','.your-domain.com'))
            or domain=='your-domain.com'):
        raise ValueError('Set a real lowercase DNS hostname you control, without scheme, path, wildcard, or port')
    try: ipaddress.ip_address(domain)
    except ValueError: pass
    else: raise ValueError('Use a DNS hostname, not an IP address')
    if not re.fullmatch(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}',email):
        raise ValueError('Set a valid ACME contact email address')
    # Compose performs $ interpolation, and Caddy substitutes settings into syntax.
    if any(char in email for char in ('$', '`', '{', '}', '#', '"', "'", '\\')):
        raise ValueError('Unsupported ACME contact email characters')
    return dict(DASHBOARD_DOMAIN=domain,ACME_EMAIL=email)


if __name__=='__main__':
    import sys
    try:
        read_settings(sys.argv[1] if len(sys.argv)>1 else '.env.website')
    except (ValueError,OSError) as error:
        raise SystemExit(str(error))
    print('Website hostname and certificate contact validated.')
