#!/usr/bin/env bash
# Reviewed installer for a fresh Ubuntu VPS, executed by its owner in the console.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "$(id -u)" -ne 0 ]; then
  echo 'Run this installer as root in your BitLaunch VPS console.' >&2; exit 1
fi
if [ ! -r /etc/os-release ]; then echo 'Cannot identify this server OS.' >&2; exit 1; fi
. /etc/os-release
if [ "${ID:-}" != ubuntu ]; then
  echo 'This installer supports Ubuntu. No packages or services were changed.' >&2; exit 1
fi
if ! command -v python3 >/dev/null; then echo 'Python 3 is required for configuration checks.' >&2; exit 1; fi
selected_port="$(python3 - "${DASHBOARD_HTTPS_PORT:-}" <<'PY'
import sys
from pathlib import Path
from scripts.website_config import https_port,read_settings
saved=read_settings('.env.website')['DASHBOARD_HTTPS_PORT'] if Path('.env.website').is_file() else '443'
print(https_port(sys.argv[1] or saved))
PY
)"
# Refuse to take over an existing web service. No existing service is stopped.
python3 - "$selected_port" <<'PY'
from pathlib import Path
import socket,errno,sys
memory=int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemTotal:')))
if memory<3_700_000: raise SystemExit('This complete dashboard stack requires at least a 4 GB VPS. No server changes made.')
import shutil
if shutil.disk_usage('.').free<10*1024**3: raise SystemExit('At least 10 GB free disk space is required. No server changes made.')
for port in (80,int(sys.argv[1])):
 sockets=[]
 try:
  for family,address in [(socket.AF_INET,('0.0.0.0',port)),(socket.AF_INET6,('::',port))]:
   if family==socket.AF_INET6 and not socket.has_ipv6: continue
   s=socket.socket(family,socket.SOCK_STREAM);sockets.append(s)
   if family==socket.AF_INET6: s.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1)
   s.bind(address)
 except OSError as error:
  if not (family==socket.AF_INET6 and error.errno in (errno.EAFNOSUPPORT,errno.EADDRNOTAVAIL)):
   raise SystemExit(f'Port {port} is unavailable: {error}. Existing services were preserved. Contact your server administrator before deployment.')
 finally:
  for s in sockets: s.close()
PY
if [ "${1:-}" = --check-only ]; then
  echo "Resource and port checks passed for HTTP 80 and HTTPS $selected_port."
  exit 0
fi
domain=${DASHBOARD_DOMAIN:-finance.stockpkg.click}
if [ ! -f .env.website ]; then
  if [ -z "${ACME_EMAIL:-}" ]; then
    read -r -p 'Email address for HTTPS certificate notices: ' ACME_EMAIL </dev/tty
  fi
  # Validate public settings without shell-evaluating configuration.
  python3 - "$domain" "$ACME_EMAIL" "$selected_port" <<'PY'
import os,sys
from scripts.website_config import validate
s=validate({'DASHBOARD_DOMAIN':sys.argv[1],'ACME_EMAIL':sys.argv[2],'DASHBOARD_HTTPS_PORT':sys.argv[3]})
fd=os.open('.env.website',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as out:
 for name,value in s.items(): out.write(name+'='+value+'\n')
PY
fi
python3 - "$selected_port" <<'PY'
import sys
from scripts.website_config import read_settings,save_settings
settings=read_settings('.env.website')
if settings['DASHBOARD_HTTPS_PORT']!=sys.argv[1]:
 settings['DASHBOARD_HTTPS_PORT']=sys.argv[1]
 save_settings('.env.website',settings)
PY
export DASHBOARD_HTTPS_PORT="$selected_port"
python3 scripts/website_config.py .env.website
if [ ! -f .local/metabase-admin.json ] && [ ! -f .local/requested-owner.json ]; then
  python3 - <<'PY'
import getpass,json,os
from pathlib import Path
from scripts.website_config import read_settings
email=read_settings('.env.website')['ACME_EMAIL']
print('Your dashboard login email will be:',email)
while True:
 password=getpass.getpass('Choose your dashboard password (14+ characters, uppercase, lowercase and a number): ')
 if len(password)<14 or not any(c.isupper() for c in password) or not any(c.islower() for c in password) or not any(c.isdigit() for c in password):
  print('Please choose a stronger password.');continue
 if password!=getpass.getpass('Confirm dashboard password: '):
  print('Passwords did not match.');continue
 break
Path('.local').mkdir(mode=0o700,exist_ok=True)
fd=os.open('.local/requested-owner.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as f: json.dump({'email':email,'password':password},f)
print('Dashboard login saved privately; your password is not printed.')
PY
fi
if ! command -v docker >/dev/null; then
  # Use Ubuntu's signed package repository. Do not remove/replace another engine.
  for package in docker-ce docker-ce-cli containerd.io podman-docker; do
    if dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed'; then
      echo "Existing $package installation needs review; no engine replacement attempted." >&2; exit 1
    fi
  done
  DEBIAN_FRONTEND=noninteractive apt-get update
  # APT keeps signature and checksum verification enabled. No curl-to-shell installer.
  DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2
fi
if ! docker compose version; then
  echo 'An existing Docker engine needs the Compose v2 plugin. No engine replacement attempted.' >&2; exit 1
fi
docker info >/dev/null
bash scripts/bootstrap_vps.sh
compose=(docker compose --env-file .env --env-file .env.website -f compose.yaml)
if [ -n "${CODEX_PROXY_CERT:-}" ]; then compose+=(-f compose.cloud.yaml); fi
compose+=(-f compose.website.yaml --profile website)
"${compose[@]}" up -d --wait --wait-timeout 300
echo 'Website proxy started. Verifying actual public HTTPS; DNS must point to this VPS.'
"${compose[@]}" run --rm website-check
echo 'The private owner login is stored in .local/metabase-admin.json. Read it privately; do not post it in chat.'
echo 'Mailbox OAuth and external AI remain disabled until explicitly configured.'
