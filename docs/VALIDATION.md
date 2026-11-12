# Validation record

Validated in the isolated development environment on 2026-11-03 using synthetic
mail only. No live mailbox OAuth token or real AI provider key was used.

- Python 3.12; pinned runtime dependencies in `requirements.txt`.
- PostgreSQL migrations apply transactionally and can be rerun without changes.
  Checksums reject changes to already-applied migrations.
- 21 unit/API/PostgreSQL regression tests cover source grounding, fabricated fields,
  privacy/auth responses, live/history overlap, invoice dedup, atomic rollback,
  lease fencing, throttling, delta reset, date-window completion, source updates,
  deletions, bounded model retries and restricted analytics permissions.
- n8n 2.46.4 imported all three shipped workflows. All three also executed with
  a synthetic Graph HTTP server and dedicated synthetic mailbox alias. The actual
  HTTP Request/If nodes, expressions, Graph response envelope, API authentication,
  commit/checkpoint logic and overlapping-message dedup were exercised. Microsoft
  authentication was deliberately replaced in these test copies only.
- Metabase's exact image is pinned by digest in Compose. The setup helper created
  a PostgreSQL analytics connection, collection, dashboard and eight cards; all
  eight SQL queries completed through the read-only role. Repeat provisioning
  updates existing objects. All Users collection access and self-service finance
  database queries are disabled using supported open-source permissions.
- Compose services start with PostgreSQL 16.14 and Python 3.12.14. The API runs
  as UID 10001 with a read-only filesystem. Its database login is not a superuser
  and cannot create roles or databases. The analytics role cannot read raw source
  tables or write application tables even after changing its read-only default.
- `bash scripts/bootstrap.sh` completed again with existing state, preserving local
  settings and avoiding workflow/dashboard duplication.
- `git diff --check`, Python compilation and shell syntax checks passed. Generated
  n8n workflow JSON is checked against its generator by the test suite. Local `.env`,
  generated owner credentials, virtualenv and smoke artifacts are ignored by Git.

## Deliberately not claimed

Actual Microsoft tenant/account authorization, real Graph delta behavior for your
mailbox, external model accuracy/availability, live historical completeness and
production ingress/backup operations require deployment-specific validation.
These are not established by a synthetic test. AI output is always a candidate,
and no monitoring result establishes a financial obligation or authorizes payment.
No email, payment, reminder or live-mailbox write was performed.

## Dedicated website deployment checks

The website overlay and Caddy configuration were prepared and validated locally.
Four additional tests passed for hostname validation and HTTPS readiness checks.
A private, loopback-only Caddy container successfully proxied the real Metabase
GUI, returned the intended security headers, denied unauthenticated dashboard API
access, and allowed the owner to view all eight cards after login. The Compose
overlay parses correctly. Existing database integration tests were not rerun for
these deployment-only changes; the 21-test application run above remains the
prior application validation record.

No public hostname, external TLS certificate, DNS change, hosting deployment or
externally reachable website has been verified. Hosting provider/domain details
and authorized hosting access are still required. The temporary local proxy is
test infrastructure, not a public dashboard link.

## Console-only VPS installer

The new `bootstrap_vps.sh` completed successfully against the local Docker
stack: it built the image, initialized analytics permissions, and provisioned
the eight dashboard cards from a restricted setup container. No host Python
virtualenv was needed for that run. All 25 application/database/website tests
passed against a disposable PostgreSQL 16.14 instance. Shell syntax checks passed
for `install_vps.sh` and `bootstrap_vps.sh`.

The Ubuntu package-installation stage has not been executed on the user's VPS.
The installer performs resource and port checks, preserves existing web services,
and uses Ubuntu-signed package repositories. Remote success is not claimed until
the VPS console run and trusted public HTTPS check complete. No DNS or mailbox
changes were made by these local tests.

Three additional initial-owner tests passed for private chosen credentials,
same-credential setup retries, rejecting invalid requested settings, and refusing
to overwrite an existing owner login. The console installer asks for the owner
password through the terminal without echo and does not print it.

## Separate HTTPS listener

All 30 application/database/website tests passed after adding explicit HTTPS
port 8443 support. The production Caddy configuration adapted successfully with
only `:8443` as its HTTPS listener and TLS-ALPN challenges disabled. A local
HTTPS test, using a trusted test CA with hostname verification enabled, exercised
health, HTML, anonymous-access denial, owner login and all eight dashboard cards.
Its HTTP redirect correctly targeted port 8443. The public ACME challenge has
not been exercised on the user's VPS.

`scripts/smoke_installer_ports.py` tested the real installer preflight in a
network-isolated container with simulated Ubuntu OS metadata: an existing port
443 listener remained running while port 8443 passed; selecting the occupied
443 or occupying 8443 caused a safe stop. No packages were installed in these
preflight tests and no existing server process was stopped or reconfigured.

## Correcting pending login details

Three targeted tests passed for `reenter_dashboard_login.py`: updating pending
credentials while preserving the host/port and protected backups; refusing to
overwrite saved accounts or accept invalid input; and checking first-run server
state while refusing initialized, timed-out or unidentified dashboard responses.
Only connection refusal (no local dashboard listener yet) permits a missing
server during this pre-installation correction. Passwords are entered through
`getpass` and never printed. No database, volume, or existing account is reset.
