# Dedicated dashboard website

The website uses a domain you control, automatic HTTPS, and private Metabase
sign-in. Only the dashboard is exposed publicly. PostgreSQL, the mailbox API and
n8n remain private. It runs the same eight finance reports as the local system.
No Outlook connection is made by deploying the website.

## Using a separate HTTPS port

To keep a different service on port 443, explicitly run:

```sh
DASHBOARD_HTTPS_PORT=8443 bash scripts/install_vps.sh
```

The dashboard then has its own normal HTTPS listener at
`https://finance.stockpkg.click:8443`, with its own Metabase login. The installer
checks ports 80 and 8443 and does not stop or reconfigure the port 443 service.
Caddy obtains certificates with HTTP-01 on port 80; TLS-ALPN challenges on port
443 are disabled. Permit inbound TCP 80 and 8443 in the host/provider firewall.
The selected port is persisted in `.env.website` and used by Metabase and the
public readiness check. Port 80 must be available; if it is occupied, setup stops
for review. No hostname changes or new DNS records are needed when the same
dashboard hostname is used on a different port.

Separate ports do not establish a security boundary against another privileged
process on the same server. Use a unique dashboard password and treat the host's
other software as part of the trust boundary. This setup does not configure a
credential-interception proxy or send mailbox credentials through one.

## Hosting requirements

Use a persistent Linux server with Docker Engine/Compose v2, Python 3.12+, and
at least 4 GB RAM (8 GB recommended for the complete n8n/Metabase/PostgreSQL stack).
A static-only website or ordinary PHP/shared-hosting plan cannot run this stack.
A VPS, dedicated server, or an equivalent container service with persistent disks
can host it. Set a subdomain such as `finance.<your-domain>` to the server's public
IP using DNS A records, and AAAA only when IPv6 is correctly routed. Ports 80 and
443 must reach Caddy. Keep SSH restricted to authorized administrators.

## Deployment

For a fresh Ubuntu VPS, use `bash scripts/install_vps.sh` from the checkout in
the VPS console as root. It asks for a certificate-contact/login email and lets
you choose a dashboard password privately in the terminal. Password input is not
echoed or printed. It defaults to
`finance.stockpkg.click`, checks memory/disk and web-port conflicts, installs the
Ubuntu-signed Docker packages only when no engine exists, and runs all Python
setup tools in the project's pinned container. It requires no SSH connection
from the assistant, no VPN, and no host virtualenv. It does not alter DNS, stop
existing web servers, reset a VPS, activate Outlook workflows or connect a mailbox.
Set the `finance` A record to the actual VPS IP in your DNS provider first. If
this hostname already has a conflicting record, review that record rather than
deleting unrelated DNS entries. Confirm the server firewall permits HTTPS/HTTP;
the installer does not rewrite firewall rules. Keep the credentials file private.

The command is intended for fresh deployment: a repeat run with ports already
occupied stops for review. For controlled upgrades use the deployment procedure
below. A failed public certificate/readiness check does not claim the website is
live. Resolve DNS/firewall errors and rerun the existing-stack startup/verification
steps rather than replacing credentials or deleting volumes.

1. Place the repository on the server. Preserve any existing private `.env`,
   `.local` owner login, n8n encryption key, and Docker volumes when upgrading.
2. Copy `deploy/website.env.example` to `.env.website` and set your actual hostname
   and certificate-contact email. These are public configuration, not credentials.
3. Run `bash scripts/deploy_website.sh`. It initializes private credentials, starts
   the stack, creates the owner login and dashboard before opening website ports,
   and then starts Caddy. HTTPS certificates are issued and renewed automatically.
4. The helper prints the actual website address only after verifying trusted TLS,
   database health, the HTML GUI response, and HTTPS security headers. Open that
   address in your browser and sign in with the private login saved in
   `.local/metabase-admin.json`. Change your owner password after first sign-in
   using Metabase's account settings; see credential rotation below.

You do not need to write application code. DNS/server access and Microsoft OAuth
consent are account-owner configuration steps. Domain registration and hosting
are not purchased by this project.

The `website` Compose profile is deliberate: simply loading the configuration
does not expose the setup wizard. The deployment script first completes private
owner setup. Keep the `caddydata` volume; it holds private certificate keys and
renewal state. Include it in encrypted, access-controlled backups alongside the
database/n8n/Metabase volumes. No credentials or database contents belong in Git.

Controlled deployment refreshes stop this project's proxy during initialization,
so a brief maintenance window is expected. If initialization fails, it stays
offline until corrected rather than exposing a setup screen.

## Private administration and mailbox connection

n8n is not an internet-facing administration console. Use an SSH tunnel from your
computer to your server, forwarding local port 5678 to its loopback port 5678.
Then open n8n in that local browser and complete its owner and read-only OAuth
setup from SETUP.md. Register the exact local callback displayed by n8n; Microsoft
permits HTTP loopback redirects for development. Keep the SSH session alive while
completing OAuth. Tenant restrictions may require an approved HTTPS callback; in
that case configure a separate protected administration hostname before consent,
instead of exposing an unclaimed n8n instance. The public dashboard hostname alone
never grants access to your mailbox or authorizes an AI provider.

Public sharing and embedding are disabled in the website configuration. Finance
reports require Metabase authentication and collection permissions. Only grant
additional reviewers the specific collection/database permissions they need.
Use MFA/SSO where your Metabase edition or hosting identity gateway supports it.

## Operations

For a browser console that disconnects, finish the initial email/password prompts
first, then run `python3 scripts/start_setup_background.py` as root. It detects
existing setup scripts and refuses duplicate launches. A new setup runs in an
independent process session with no terminal input. It records progress privately
in `.local/setup.log` and completion in `.local/setup-status.json`. Reconnect the
console and run `tail -n 25 /opt/mailboxreader/.local/setup.log` to inspect progress.
It may pause this project's website during private setup; other services are not
stopped. An existing active installer is left running and may still need input
in its original console. No credentials are printed by this launcher.

If you mistyped the initial email/password and no dashboard owner has yet been
created, run `python3 scripts/reenter_dashboard_login.py` in the VPS console. It
prompts privately, checks the local setup state, backs up pending settings under
`.local/login-backup-*`, and updates only the pending login/contact email. The
hostname and HTTPS port are retained. It refuses to overwrite an existing saved
owner or reset an already initialized dashboard. After success, rerun the
installer with `DASHBOARD_HTTPS_PORT=8443` for an alternate-port deployment.
This helper does not delete databases or Docker volumes. Keep backup files private.

- HTTPS verification failures are deployment failures, not success. Inspect DNS,
  port reachability and `docker compose ... logs website`; never disable certificate
  verification to work around them. Caddy requires certificate-authority network
  access and working public DNS; the development sandbox is not a substitute for
  your hosting provider.
- Once the owner password is changed, the generated password file is stale. Use
  `scripts/provision_metabase.py` with a securely supplied administrator API key
  for future dashboard updates, rather than resetting or overwriting the owner.
  For normal restarts run Compose with `.env`, `.env.website`, `compose.yaml`,
  `compose.website.yaml`, and the `website` profile; the bootstrap script is for
  initialization and controlled refreshes, not every routine restart.
- Existing data is not automatically copied from a development machine to a new
  host. For a fresh deployment it starts empty. If a migration is requested, use
  encrypted PostgreSQL backups plus n8n/Metabase state and the encryption key;
  validate restoration before changing DNS. The current project contains no real
  mailbox data to migrate.
- Monitor disk capacity, backup/restore health, certificate renewal, ingestion and
  extraction health, and container updates. Initial hosting deployment and domain
  ownership must be verified before claiming an externally accessible website.
