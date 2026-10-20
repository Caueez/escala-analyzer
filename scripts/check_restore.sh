#!/usr/bin/env bash
# Restores to a NEW database, compares key tables, then drops ONLY that test DB.
set -euo pipefail
compose_project="${1:?provide isolated Compose project name}"
env_file="${2:?provide env file}"
export ESCALA_ENV_FILE="$(realpath "$env_file")"
restore_database="escala_restore_$(date +%s)_$RANDOM"
backup_path="$(mktemp)"
chmod 600 "$backup_path"
compose=(docker compose --env-file "$env_file" -p "$compose_project")
cleanup() {
  "${compose[@]}" exec -T db sh -c 'dropdb --if-exists -U "$POSTGRES_USER" "$1"' sh "$restore_database" >/dev/null
  rm -f "$backup_path"
}
trap cleanup EXIT
"${compose[@]}" exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$backup_path"
"${compose[@]}" exec -T db sh -c 'createdb -U "$POSTGRES_USER" "$1"' sh "$restore_database"
"${compose[@]}" exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" --no-owner --no-acl -d "$1"' sh "$restore_database" < "$backup_path"
# A portability restore uses --no-acl; restore the runtime grants explicitly.
"${compose[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$1" -v ON_ERROR_STOP=1 -c "GRANT USAGE ON SCHEMA public TO escala; GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO escala; REVOKE INSERT,UPDATE,DELETE ON alembic_version FROM escala;"' sh "$restore_database" >/dev/null
# Compare counts and migration revision without dumping credentials or payloads.
for table in organizations users projects jobs audit_events; do
  original_count="$("${compose[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT count(*) FROM $1"' sh "$table")"
  restored_count="$("${compose[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$1" -tAc "SELECT count(*) FROM $2"' sh "$restore_database" "$table")"
  test "$original_count" = "$restored_count"
done
revision="$("${compose[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$1" -tAc "SELECT version_num FROM alembic_version"' sh "$restore_database")"
test "$revision" = "0001_saas"
printf 'Backup restored to a separate database; table counts and migration revision verified.\n'
