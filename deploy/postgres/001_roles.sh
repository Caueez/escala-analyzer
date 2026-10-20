#!/bin/sh
# Run only during initialization of a NEW PostgreSQL volume. Never print secrets.
set -eu
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=ON_ERROR_STOP=1 --set=runtime_password="$ESCALA_DB_PASSWORD" \
  --set=migrator_password="$ESCALA_MIGRATOR_PASSWORD" --set=db_name="$POSTGRES_DB" <<'SQL'
CREATE ROLE escala LOGIN PASSWORD :'runtime_password';
CREATE ROLE escala_migrator LOGIN PASSWORD :'migrator_password';
REVOKE CONNECT, TEMPORARY ON DATABASE :"db_name" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db_name" TO escala, escala_migrator;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO escala;
GRANT USAGE, CREATE ON SCHEMA public TO escala_migrator;
ALTER DEFAULT PRIVILEGES FOR ROLE escala_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO escala;
ALTER DEFAULT PRIVILEGES FOR ROLE escala_migrator IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO escala;
SQL
