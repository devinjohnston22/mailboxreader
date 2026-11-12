#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/website_config.py .env.website
compose=(docker compose --env-file .env --env-file .env.website -f compose.yaml)
if [ -n "${CODEX_PROXY_CERT:-}" ]; then compose+=(-f compose.cloud.yaml); fi
compose+=(-f compose.website.yaml --profile website)
# Create local credentials before Compose parses its required variables.
if [ ! -f .env ]; then python3 scripts/init_settings.py; fi
# On a refresh, stop only this project's proxy before private initialization.
# Never leave a previous proxy exposing an owner-setup or credential-rotation flow.
"${compose[@]}" stop website
bash scripts/bootstrap.sh
"${compose[@]}" up -d --wait --wait-timeout 300
.venv/bin/python scripts/verify_website.py
