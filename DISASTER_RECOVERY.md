# Disaster recovery runbook

Last reviewed: 11 giugno 2026

This document is the procedure when something has gone wrong and you need to
get the service back. It assumes the reader has Docker + bash and access to
the backups directory. Keep it short and step-by-step; the wrong time to
discover a missing step is at 3am.

## What's stored where

| Tier | Where | What | Rebuildable? |
|---|---|---|---|
| Source PDFs | `./sample/`, committed to git | The 3 indexed documents | Yes (from git) |
| Postgres | `conv_agent_postgres` container, volume `postgres_data` | Users, conversations, messages, qa_log | **No — must be backed up** |
| Qdrant | `conv_agent_qdrant` container, volume `qdrant_storage` | 357 vector chunks of the source PDFs | Yes (re-index from PDFs, ~30s + ~$0.02 OpenAI) |
| Secrets | `.env` (not in git) | API keys, JWT secret, DB password | **No — must be backed up out-of-band (Vault / 1Password / etc.)** |
| Containers + code | Docker images + git | Application | Yes (git) |

**Implication:** Postgres is the only thing whose loss is unrecoverable from
zero. The Qdrant snapshot is a convenience — fast recovery vs ~30 seconds of
re-indexing.

## RTO / RPO targets

- **RTO** (recovery time objective): **< 30 minutes** from "host is reachable
  again" to "service answering chats". Most of that is pulling images and
  running the restore script.
- **RPO** (recovery point objective): **last 24h** if backups run nightly,
  **last hour** if hourly. Conversation loss is annoying; `qa_log` loss
  is more serious for audit purposes.

Adjust these once we know the actual deployment shape.

---

## 1. Backups

### Manual one-shot

From the project root:

```bash
# Both at once (Postgres + Qdrant snapshot)
bash scripts/backup_all.sh

# Or individually
bash scripts/backup_postgres.sh
bash scripts/backup_qdrant.sh
```

Files land in `./backups/`:

```
backups/postgres_conv_agent_20260601_120000Z.sql.gz
backups/qdrant_conv_agent_chunks_20260601_120000Z.snapshot
```

Sizes: Postgres dump is a few KB right now, Qdrant snapshot is ~10–20 MB
(grows with the corpus).

### Scheduled (production)

Pick **one** of these, whichever matches your deployment environment:

**A. cron on the docker host** — simplest:

```cron
# Nightly at 02:00 UTC
0 2 * * * cd /opt/conv_agent && BACKUP_DIR=/srv/backups bash scripts/backup_all.sh >> /var/log/conv_agent_backup.log 2>&1
```

**B. systemd timer** — preferred over cron for journal integration:

```ini
# /etc/systemd/system/conv-agent-backup.service
[Service]
Type=oneshot
WorkingDirectory=/opt/conv_agent
Environment=BACKUP_DIR=/srv/backups
ExecStart=/usr/bin/bash scripts/backup_all.sh

# /etc/systemd/system/conv-agent-backup.timer
[Timer]
OnCalendar=daily
RandomizedDelaySec=1h
Persistent=true
```

**C. Sidecar container in compose** — for k8s/swarm where the host is
ephemeral:

```yaml
backup:
  image: alpine:3.20
  volumes:
    - ./scripts:/scripts:ro
    - ./backups:/backups
    - /var/run/docker.sock:/var/run/docker.sock
  entrypoint: ["sh", "-c", "apk add docker-cli docker-compose-plugin curl python3 && cd /workspace && bash /scripts/backup_all.sh"]
  profiles: ["backup-on-demand"]
```

### Off-site copy (always)

The backup files are useless if the same host they protect is also where
they live. Push to S3 / Backblaze / managed object store immediately after
each run:

```bash
# Append to cron entry
&& aws s3 sync /srv/backups s3://your-bucket/conv-agent/ --storage-class STANDARD_IA
```

Set bucket lifecycle to delete > 90 days, transition to Glacier > 30 days,
versioning **on**.

### Retention

In `./backups/`, prune older than 14 days locally:

```bash
find ./backups -name "postgres_*.sql.gz" -mtime +14 -delete
find ./backups -name "qdrant_*.snapshot" -mtime +14 -delete
```

The long-term archive lives in S3 with its own lifecycle.

---

## 2. Restore

### 2a. Restore Postgres from a dump

```bash
bash scripts/restore_postgres.sh ./backups/postgres_conv_agent_<TIMESTAMP>.sql.gz
```

The script:
1. Prompts for confirmation (Enter to continue, Ctrl-C to abort).
2. Streams the gunzipped dump into `psql` inside the postgres container.
3. Uses `--clean --if-exists`, so it **drops every existing table** before
   restoring. Active sessions will be killed; the API will return 5xx until
   you restart it.

After the restore:

```bash
# Restart the API to clear cached connections
docker compose restart api

# Verify (see section 3)
```

### 2b. Restore Qdrant from a snapshot

Qdrant snapshot restore goes through a different endpoint — the snapshot
must be **uploaded** to the running Qdrant. There's no destructive `--clean`
equivalent, so you may need to delete the collection first if it exists:

```bash
# (Optional) Drop the existing collection
curl -fsS -X DELETE http://localhost:6333/collections/conv_agent_chunks

# Upload + restore the snapshot
curl -fsS -X POST \
  "http://localhost:6333/collections/conv_agent_chunks/snapshots/upload" \
  -H "Content-Type: multipart/form-data" \
  -F "snapshot=@./backups/qdrant_conv_agent_chunks_<TIMESTAMP>.snapshot"

# Verify
curl -fsS http://localhost:6333/collections/conv_agent_chunks | python -m json.tool
# expect: status="green", points_count=357 (or whatever the corpus size is)
```

### 2c. Rebuild Qdrant from source (alternative)

If a snapshot isn't available — say after a long outage where backups
expired — re-index from the source PDFs in `./sample/`:

```bash
docker compose run --rm indexer python analyze_chunks.py   # produces ./out/chunks_*.jsonl
docker compose run --rm indexer python index.py             # uploads to Qdrant
docker compose run --rm indexer python smoke_query.py       # 6-query sanity check
```

Cost: ~30 seconds + ~$0.02 of OpenAI embeddings. Note this requires the
source PDFs to still be in `./sample/`; they're in git so this works on
any clean clone.

---

## 3. Verify after restore

### Postgres

```bash
docker compose exec postgres psql -U conv_agent -d conv_agent -c "\dt"
# expect: alembic_version, conversations, messages, qa_log, users

docker compose exec postgres psql -U conv_agent -d conv_agent -c "
  SELECT
    (SELECT count(*) FROM users) AS users,
    (SELECT count(*) FROM conversations) AS conversations,
    (SELECT count(*) FROM messages) AS messages,
    (SELECT count(*) FROM qa_log) AS qa_log;
"
# expect: row counts roughly matching what you backed up

docker compose exec postgres psql -U conv_agent -d conv_agent -c "
  SELECT version_num FROM alembic_version;
"
# expect: 0001 (or whatever the latest migration is)
```

### Qdrant

```bash
curl -fsS http://localhost:6333/collections/conv_agent_chunks | python -m json.tool
# expect: {"result":{"status":"green","points_count":357,...},"status":"ok"}

# End-to-end retrieval works:
docker compose run --rm indexer python smoke_query.py
# expect: 6/6 probe queries return the right top-1 source
```

### API

```bash
# Auth still works
curl -fsS -X POST http://localhost:8002/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"<known-user>","password":"<known-password>"}' \
  | python -m json.tool
# expect: access_token + refresh_token

# Chat works (replace TOKEN with the access_token above)
curl -fsS -X POST http://localhost:8002/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer TOKEN" \
  -d '{"message":"Quali sono gli obblighi dei TSO in materia di tensione?"}' \
  | python -m json.tool
# expect: 4–6 segments, at least 1 source from CELEX SOGL
```

If all three pass, you're back online.

---

## 4. Common scenarios

### "Postgres volume deleted by accident"

1. `docker compose up -d postgres` (recreates the volume empty)
2. `docker compose run --rm api alembic upgrade head` (recreates the schema)
3. `bash scripts/restore_postgres.sh ./backups/postgres_<latest>.sql.gz`
4. Restart API: `docker compose restart api`
5. Verify (section 3).

### "Qdrant volume deleted"

1. `docker compose up -d qdrant` (recreates the volume empty)
2. Either restore the snapshot (2b) **or** rebuild from source (2c).
3. Verify (section 3).

### "Whole docker host is gone, fresh provision"

1. Provision new host with Docker.
2. `git clone <repo> /opt/conv_agent && cd /opt/conv_agent`
3. Restore secrets to `.env` from your secret vault (never committed).
4. Restore the latest backups from S3 → `./backups/`.
5. `docker compose build` (or `docker compose pull` if you publish images).
6. `docker compose up -d postgres qdrant` (start the stateful services).
7. `docker compose run --rm api alembic upgrade head` (schema).
8. `bash scripts/restore_postgres.sh ./backups/postgres_<latest>.sql.gz`
9. `bash scripts/restore_qdrant.sh` (the manual steps in 2b) OR re-index (2c).
10. `docker compose up -d api frontend`.
11. Verify (section 3).
12. Tell users.

Total time target: 30 minutes if backups are at hand and `.env` is recoverable.

### "Database migration broke things"

1. Note the failing revision: `docker compose run --rm api alembic current`.
2. Roll back one step: `docker compose run --rm api alembic downgrade -1`.
3. Fix the migration file in `api/alembic/versions/`.
4. Re-apply: `docker compose run --rm api alembic upgrade head`.
5. If the failed migration corrupted data, restore from the most recent
   pre-migration backup (2a).

### "Compromised JWT secret"

Rotate it:

1. Generate a new one: `python -c "import secrets; print(secrets.token_urlsafe(48))"`
2. Update `JWT_SECRET` in `.env` and your secret vault.
3. `docker compose restart api`. **Every active session becomes invalid** —
   users must re-login. There's no per-session revocation in v1; rotating
   the secret is the revocation mechanism.

### "Need to delete a specific user's data (GDPR right to erasure)"

```sql
-- Inside docker compose exec postgres psql -U conv_agent -d conv_agent
-- Conversations + messages cascade automatically:
DELETE FROM users WHERE email = '<their-email>';

-- qa_log rows survive but their user_id is nulled (ON DELETE SET NULL),
-- so the audit trail remains intact but is no longer linkable back.
-- If the regulation requires deleting the audit content too (full erasure),
-- uncomment the line below — but be aware this loses the regulatory
-- accountability for those interactions:
-- DELETE FROM qa_log WHERE user_id IS NULL AND query IN (
--   SELECT q FROM ...  -- only the affected user's rows
-- );
```

---

## 5. Things this runbook DOES NOT cover

These are intentionally out of scope and need their own runbook before going
broadly live:

- **Failover** (active-passive or active-active) — single-host today.
- **Replica reset** when running multi-replica Postgres.
- **Qdrant cluster recovery** — single-node today.
- **Secret rotation cadence** beyond a one-time emergency rotation.
- **Tabletop drill schedule** — book one for the team **before** the first
  prod incident.

Add to that list as the deployment grows.
