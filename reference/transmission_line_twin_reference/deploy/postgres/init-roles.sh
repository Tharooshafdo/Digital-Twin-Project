#!/bin/sh
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v app_password="$APP_PASSWORD" -v reader_password="$READER_PASSWORD" <<'SQL'
CREATE ROLE dt_app LOGIN PASSWORD :'app_password';
CREATE ROLE dt_reader LOGIN PASSWORD :'reader_password';
GRANT CONNECT ON DATABASE twin TO dt_app, dt_reader;
GRANT USAGE, CREATE ON SCHEMA public TO dt_app;
GRANT USAGE ON SCHEMA public TO dt_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE dt_app IN SCHEMA public
    GRANT SELECT ON TABLES TO dt_reader;
SQL
