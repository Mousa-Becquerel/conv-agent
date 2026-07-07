#!/usr/bin/env bash
#
# Restore Postgres from a gzipped pg_dump file.
#
# DANGEROUS: drops every object in the target database (the dump uses
# `--clean --if-exists`) before recreating them. Confirm twice before
# running in prod.
#
# Usage:
#   scripts/restore_postgres.sh ./backups/postgres_conv_agent_20260601_120000Z.sql.gz

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <postgres_dump.sql.gz>" >&2
  exit 2
fi

dump_file="$1"
DB_USER="${POSTGRES_USER:-conv_agent}"
DB_NAME="${POSTGRES_DB:-conv_agent}"

if [[ ! -f "${dump_file}" ]]; then
  echo "ERROR: file not found: ${dump_file}" >&2
  exit 2
fi

cat <<EOF
WARNING: this will WIPE every object in the '${DB_NAME}' database and
restore from ${dump_file}. Active sessions will be disconnected.

Press ENTER to continue, Ctrl-C to abort.
EOF
read -r _

# Stream the gunzipped dump straight into psql in the postgres container.
gunzip -c "${dump_file}" | docker compose exec -T postgres \
  psql -U "${DB_USER}" -d "${DB_NAME}" --set ON_ERROR_STOP=on -1

echo
echo "OK: restore complete from ${dump_file}"
echo "Next: verify with the queries in DISASTER_RECOVERY.md \"Verify restore\"."
