# Mailbox Reader

Read-only Outlook finance intelligence: resumable n8n ingestion, evidence-backed
AI extraction, PostgreSQL storage, and Metabase review dashboards. Nothing sends
mail, modifies Outlook messages, initiates payments, or declares a debt overdue.

Start with [setup](docs/SETUP.md), [security rules](docs/SECURITY.md),
[specification](docs/CODEX_TASK.md), and [historical scan](docs/HISTORICAL_SCAN.md).
For a dedicated domain with private login and automatic HTTPS, see
[website deployment](docs/WEBSITE.md).

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

`docker compose up --build -d` starts PostgreSQL, the API, n8n, and Metabase
after you supply settings from the setup guide. Workflows in `workflows/` are
importable and deliberately inactive. Live access requires your Microsoft OAuth
authorization in n8n. Synthetic tests require no Microsoft credentials.
