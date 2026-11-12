#!/usr/bin/env bash
# Start the application without installing Python packages on the host.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f .env ]; then python3 scripts/init_settings.py; fi
mkdir -p .local
chmod 700 .local
export SETUP_UID="$(id -u)" SETUP_GID="$(id -g)"
compose=(docker compose)
if [ -n "${CODEX_PROXY_CERT:-}" ]; then compose+=(-f compose.yaml -f compose.cloud.yaml); fi
"${compose[@]}" up --build -d --wait --wait-timeout 300
"${compose[@]}" run --rm analytics-setup
if [ ! -f .local/workflows-imported ]; then
  for workflow in outlook_live.json outlook_history.json extract_and_monitor.json; do
    "${compose[@]}" exec -T n8n n8n import:workflow --input="/workflows/$workflow"
  done
  touch .local/workflows-imported
fi
"${compose[@]}" run --rm dashboard-setup
echo 'Dashboard initialized privately. Outlook workflows remain inactive.'
