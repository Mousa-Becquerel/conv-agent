#!/usr/bin/env bash
#
# Postgres backup. Dumps the conv_agent database to a gzip'd .sql file in
# ./backups/ named with a UTC timestamp. Run from the project root so the
# `docker compose` invocation finds the compose file.
#
# Usage:
#   scripts/backup_postgres.sh                # default ./backups dir
#   BACKUP_DIR=/srv/backups scripts/backup_postgres.sh
#
# Designed to be safe to cron: idempotent, exits non-zero on any failure,
# never overwrites an existing file (the timestamp is per-second).

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
DB_USER="${POSTGRES_USER:-conv_agent}"
DB_NAME="${POSTGRES_DB:-conv_agent}"

timestamp="$(date -u +%Y%m%d_%H%M%SZ)"
file="${BACKUP_DIR}/postgres_${DB_NAME}_${timestamp}.sql.gz"

mkdir -p "${BACKUP_DIR}"

# --clean --if-exists makes the dump self-contained: the restore drops every
# object before recreating it, so a partially-populated DB doesn't conflict.
# pg_dump runs inside the postgres container; we pipe stdout to host gzip.
docker compose exec -T postgres pg_dump \
  -U "${DB_USER}" -d "${DB_NAME}" \
  --clean --if-exists --no-owner --no-privileges \
  | gzip --best > "${file}"

bytes="$(wc -c < "${file}" | tr -d ' ')"
echo "OK: postgres dump -> ${file} (${bytes} bytes)"
