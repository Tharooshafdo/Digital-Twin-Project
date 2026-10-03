#!/bin/sh
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=app_password="$APP_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE dt_app LOGIN PASSWORD %L', :'app_password') \gexec
GRANT CONNECT ON DATABASE twin TO dt_app;
GRANT USAGE, CREATE ON SCHEMA public TO dt_app;
SQL
