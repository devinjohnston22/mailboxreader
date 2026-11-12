#!/usr/bin/env bash
set -euo pipefail
psql --username "$POSTGRES_USER" --dbname postgres --set=app_pwd="$MAILBOX_DB_PASSWORD" --set=ON_ERROR_STOP=1 <<'SQL'
SELECT format('CREATE ROLE mailbox LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L', :'app_pwd') \gexec
CREATE DATABASE mailbox OWNER mailbox;
SQL
