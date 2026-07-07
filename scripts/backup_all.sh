#!/usr/bin/env bash
#
# Convenience wrapper: run both Postgres + Qdrant backups in sequence.
# Designed to be the cron-scheduled entry point in prod.
#
# Usage:
#   scripts/backup_all.sh
#   BACKUP_DIR=/srv/backups scripts/backup_all.sh

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"${script_dir}/backup_postgres.sh"
"${script_dir}/backup_qdrant.sh"

echo
echo "OK: backups complete in ${BACKUP_DIR:-./backups}"
