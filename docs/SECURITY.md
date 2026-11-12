# Security rules

- **No mailbox access without explicit OAuth authorization.** Shipped n8n workflows
  are inactive and contain placeholder credential references. Only delegated
  `offline_access https://graph.microsoft.com/Mail.Read` scopes are permitted.
  Do not grant `Mail.ReadWrite`, `Mail.Send`, application-wide permissions or
  `.default` scopes. Application code has no Microsoft token and performs no Graph
  calls; n8n's credential store owns token refresh. Revoke consent in Microsoft
  account/tenant settings to stop access, and deactivate workflows.
- Graph nodes issue GET only; redirects are disabled. Continuation URLs must use
  exact HTTPS `graph.microsoft.com/v1.0/me/`. Do not enable automatic URL following
  from email content. Do not retrieve attachments or embedded links.
- Email and model output are hostile input. No tools, expressions, commands, SQL,
  HTML, payment links or instructions from them are executed. AI output passes
  strict schema and evidence validation; SQL uses bound parameters. Prompts alone
  are not a security boundary. Human review remains mandatory for extracted facts.
- External AI is disabled by default. Setting `AI_ENABLED=true` explicitly consents
  to sending text email subjects, sender addresses and bodies to OpenAI. Supply
  your own key securely. `store=false` is requested; provider contractual retention
  policies still apply. Obtain the mailbox/data owner's approval before enabling
  this option. No live AI request is needed for tests.
- API endpoints except minimal health require a random 32+ character bearer token.
  All business data is private. Compose binds UI/API ports to loopback; deployment
  outside a trusted local machine requires HTTPS, authenticated ingress and a
  reviewed firewall. n8n's insecure-cookie setting is for loopback development;
  enable secure cookies when putting it behind HTTPS. Do not publish workflows or
  dashboards publicly or expose n8n to untrusted workflow authors.
- Never commit secrets. `.env` is generated with mode 0600 and is ignored. Keep
  n8n encryption keys and backups private. No email payloads are saved in n8n
  execution history, logs or test artifacts. Manual execution output is visible
  while inspecting an active run: do not share it. Configure infrastructure logs
  without body/header capture. Failed model responses are not persisted.
- Raw source text is retained in PostgreSQL for reproducible evidence. The raw
  source may include personal or financial details. Use encrypted disks/backups,
  least-privilege operator accounts and a documented retention/deletion policy
  before real ingestion. Metabase receives only SELECT on named views, never the
  owner connection. Evidence excerpts redact long numeric identifiers, but remain
  sensitive; redaction is not a general DLP guarantee.
- Payment-method intelligence stores method categories only, not structured bank
  details, routing numbers, card numbers or payment credentials. Never initiate or
  recommend payments based on these findings. Contacts are unverified candidates.
- Review flags require an authenticated operator and explanatory note. They only
  affect local reporting and never update Outlook. Audit events contain identifiers
  and status/counts, not mail bodies. Single-instance token authentication identifies
  the local operator collectively; deploy an identity gateway for named-user audits.

## Operations

Back up all PostgreSQL/n8n/Metabase volumes with encryption; test restores and
restrict backup access. Keep OAuth client secrets in n8n credentials, not workflows.
Rotate API tokens and the dashboard database password on suspected exposure;
changing `N8N_ENCRYPTION_KEY` without re-encrypting credentials makes them unusable.
To purge a mailbox: deactivate workflows, stop extraction, delete its `messages`
(cascades aliases, versions and facts), `sync_state` and `monitor_settings`, then
remove relevant reviews/audit records according to retention policy. Also expire
backups and clear Metabase query caches. Obtain approval before destructive purges.
