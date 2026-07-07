#!/usr/bin/env bash
#
# Qdrant snapshot. Triggers a server-side snapshot of the conv_agent_chunks
# collection, then downloads it to ./backups/. The snapshot is a self-
# contained binary of the collection's vectors + payloads + index.
#
# Re-indexing from the source PDFs would also work (~30s + $0.02 of OpenAI
# embeddings on the current corpus), so this snapshot is for fast recovery,
# not last-resort.
#
# Usage:
#   scripts/backup_qdrant.sh
#   BACKUP_DIR=/srv/backups scripts/backup_qdrant.sh

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
COLLECTION="${COLLECTION_NAME:-conv_agent_chunks}"
QDRANT_URL="${QDRANT_URL_HOST:-http://localhost:6333}"

mkdir -p "${BACKUP_DIR}"

timestamp="$(date -u +%Y%m%d_%H%M%SZ)"
final_file="${BACKUP_DIR}/qdrant_${COLLECTION}_${timestamp}.snapshot"

echo "==> Triggering snapshot of '${COLLECTION}' on ${QDRANT_URL}..."
# POST returns: {"result": {"name": "..."}, "status": "ok"}
snapshot_name="$(
  curl -fsS -X POST "${QDRANT_URL}/collections/${COLLECTION}/snapshots" \
    | python -c 'import json,sys; print(json.load(sys.stdin)["result"]["name"])'
)"
echo "    server-side snapshot: ${snapshot_name}"

echo "==> Downloading to ${final_file}..."
curl -fsS "${QDRANT_URL}/collections/${COLLECTION}/snapshots/${snapshot_name}" \
  -o "${final_file}"

bytes="$(wc -c < "${final_file}" | tr -d ' ')"
echo "OK: qdrant snapshot -> ${final_file} (${bytes} bytes)"

# Clean up the in-Qdrant copy so snapshots don't accumulate forever.
# Failure here is non-fatal; the local download is what matters.
curl -fsS -X DELETE \
  "${QDRANT_URL}/collections/${COLLECTION}/snapshots/${snapshot_name}" \
  >/dev/null 2>&1 || true
