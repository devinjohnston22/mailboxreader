# Setup and operation

## Local stack (no coding needed)

Install Docker Engine with Compose v2 and Python 3.12+. From the checkout run:

```sh
bash scripts/bootstrap.sh
```

The helper generates private random settings if `.env` is absent, fixes the scan
boundary, builds/starts services, creates a read-only analytics role, imports
inactive workflows and provisions Metabase with eight dashboard cards. Existing
settings are never overwritten. Services bind only
to loopback: n8n port 5678, API 8000, Metabase 3000. PostgreSQL is internal only.
Open these ports in your own local browser. For cloud deployments use your
platform's authenticated ingress, not public unauthenticated port forwarding.

On repeat setup, the `.local/workflows-imported` marker prevents template imports
from duplicating your configured workflows. If you intentionally delete the n8n
volume, remove this marker before bootstrapping again. Never activate duplicate
schedules. Dependencies, state and credentials live in
Docker volumes. Processes must be restarted after a machine restoration.

## Outlook authorization (required only for real mail)

1. Complete n8n's owner-account setup. Register a Microsoft Entra application for
   the intended account type. Set its Web redirect URI to the exact OAuth callback
   displayed by n8n (typically your n8n origin plus `/rest/oauth2-credential/callback`).
2. Create a **generic OAuth2 API** credential named `Outlook Mail.Read only`:
   authorization-code grant; auth URL
   `https://login.microsoftonline.com/<tenant>/oauth2/v2.0/authorize`; token URL
   `https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token`; your client ID
   and client secret; client authentication in body; scope
   `offline_access https://graph.microsoft.com/Mail.Read`. Use the intended tenant
   or `consumers` for personal accounts. Do not use broader/default scopes.
3. Connect the credential and explicitly authorize the Microsoft consent screen.
   Check that its only mailbox permission is read access. This is the authorization
   boundary: do not activate either Outlook workflow before consent.
4. Create a Header Auth credential named `Mailbox Reader API`, header name
   `Authorization`, value `Bearer ` followed by the `API_TOKEN` from private `.env`.
   Assign it to all API nodes in the three imported workflows. Assign the generic
   OAuth credential to both `Read Outlook page` nodes. Placeholder IDs must be
   replaced by selecting your real credentials in n8n.
5. Confirm `MAILBOX_ID`, `LIVE_FOLDER`, `HISTORY_START`, `HISTORY_END` and threshold
   in `.env`. Use a stable mailbox alias; one mailbox per stack. Restart the API
   with `docker compose up -d api` after settings changes. Run one manual read-only
   live page after authorization, inspect status, then activate live/history schedules.

No Microsoft client secret, token or live mailbox is needed to develop or test.

In a restricted cloud environment, allow `graph.microsoft.com` and
`login.microsoftonline.com` for the authorized OAuth/read workflow, plus
`api.openai.com` only if you opt in to external extraction. Package registries and
Docker image registries are needed for installation. `compose.cloud.yaml` supplies
the managed CA bundle to Python and Node without disabling TLS verification;
the bootstrap helper selects it when `CODEX_PROXY_CERT` is present. Use the existing
isolated checkout; no Git worktree is needed.

## AI extraction

By default messages queue without external AI calls. To opt in, read SECURITY.md,
set `AI_API_KEY` securely and `AI_ENABLED=true` in `.env`, restart API, then enable
the extraction/monitor workflow. The worker processes one message per minute,
with a 100,000-character maximum and five bounded retries. Increase throughput
using extra schedule frequency only after checking provider limits. Unsupported
large messages remain failed for manual review; content is never silently cut.
Only explicit ISO currency codes and unambiguous due dates are accepted. Currency
symbols alone and ambiguous numeric dates must be omitted by the model.

## Metabase dashboard

The bootstrap helper initializes a new local Metabase instance automatically.
Its generated owner login is in private `.local/metabase-admin.json`; open that
file locally to sign in. It never prints the password. The finance dashboard is
hidden from the broad All Users group, and that group's self-service queries for
the finance database are disabled. Explicit administrator/reviewer groups retain
their own grants. This uses supported open-source permissions; commercial data
blocking/export controls are not assumed. All eight queries are executed during
setup through the analytics role. Re-running `scripts/bootstrap_metabase.py`
updates the dashboard without duplicating cards. Use an administrator account
to explicitly grant access to any additional trusted finance-review group.

For an already configured Metabase instance without the generated login file,
use the manual connection/API-key route below instead of replacing its owner.

Complete Metabase's first-run UI. Add a PostgreSQL database with host `postgres`,
port `5432`, database `mailbox`, username `mailbox_analytics`, and the private
`ANALYTICS_PASSWORD`. Use the **analytics** login, never the `mailbox` owner.
Disable public sharing and query caching for sensitive review data. Restrict the
finance collection and database permissions to authorized reviewers in the UI;
Metabase administrators retain administrative access. Do not enable public links.

Create a Metabase administrator API key in its admin UI. Supply `METABASE_API_KEY` securely to
your shell and set `METABASE_DATABASE_ID` to the numeric database ID shown in the
Metabase URL. With the project's Python dependencies installed run:

```sh
python scripts/provision_metabase.py
```

This repeatable helper creates/updates the restricted `Mailbox Reader — finance review`
collection, dashboard and eight cards from `dashboards/cards.json`. It does not
create public links. It removes All Users access to the collection and disables
self-service queries for that group on this database, preserving other groups.
An administrator key is required to apply these permissions. No key is saved.

## Review and checks

`GET /monitor` returns possible overdue findings with candidate keys. An authorized
operator can POST `/review/{key}` with `status` (`open`, `paid`, `dismissed`) and a
human explanatory `note`. This changes local reporting only. Use the source-evidence
card to follow corroborating source versions and Outlook links. Finance totals and
payment hints cannot replace your accounting ledger.
For an interactive review without writing requests or code, run
`.venv/bin/python scripts/review.py`; it prompts for a decision and reason.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
# To run integration tests as well, supply a DISPOSABLE PostgreSQL DSN:
TEST_DATABASE_URL=postgresql://postgres:synthetic-test-only@127.0.0.1:55432/postgres \
  .venv/bin/python -m unittest discover -s tests -v
```

Integration tests truncate application tables in that database. Never point them
at a live mailbox database. CI starts a dedicated PostgreSQL service. Unit tests
use a mocked AI transport; integration tests use synthetic email and no OAuth.
`python scripts/generate_workflows.py` regenerates the importable JSON deterministically.
With the stack running, `.venv/bin/python scripts/smoke_stack.py` executes all three
workflows against a synthetic Graph server and separate mailbox alias, verifies
checkpoint/dedup behavior, then removes its synthetic mail. Its inactive workflows
are labeled `SYNTHETIC ONLY` and can be deleted in n8n after testing. The helper
never attaches Microsoft credentials or calls Microsoft. Normal restarts only need
`docker compose up -d`; do not rely on a development server surviving a snapshot.

API health requires the migrated database. `sync_health` and `extraction_health`
cards show progress and failures. A 401/403 from Graph needs consent/tenant review;
429 needs the persisted backoff; failed extraction needs source/model review.
No automatic email alerts are sent: monitoring is a private dashboard and API.
