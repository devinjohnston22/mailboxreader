#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f .env ]; then python3 scripts/init_settings.py; fi
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
.venv/bin/pip install --disable-pip-version-check -r requirements.txt
compose=(docker compose)
if [ -n "${CODEX_PROXY_CERT:-}" ]; then compose+=(-f compose.yaml -f compose.cloud.yaml); fi
"${compose[@]}" up --build -d --wait --wait-timeout 300
"${compose[@]}" run --rm analytics-setup
mkdir -p .local
chmod 700 .local
if [ ! -f .local/workflows-imported ]; then
  for workflow in /workflows/outlook_live.json /workflows/outlook_history.json /workflows/extract_and_monitor.json; do
    "${compose[@]}" exec -T n8n n8n import:workflow --input="$workflow"
  done
  touch .local/workflows-imported
fi
.venv/bin/python scripts/bootstrap_metabase.py
echo 'Stack started. Workflows are inactive. Complete n8n owner setup and read-only OAuth configuration in docs/SETUP.md.'
