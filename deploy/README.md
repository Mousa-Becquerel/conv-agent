# EC2 deployment — conv-agent

Target: `https://dev.solarintelligence.ai/conv-agent/` on the shared
`solar-intelligence-dev` EC2. conv-agent runs fully isolated (own Postgres,
own Qdrant, own Docker network, own memory limits); the only shared surface
is the Caddy ingress on `:443`.

## First-time setup on the EC2 (one-time)

1. SSH in:
   ```bash
   ssh -i ~/Downloads/SI_dev.pem ec2-user@13.63.241.80
   ```

2. Clone the repo:
   ```bash
   cd ~
   git clone git@github.com:Mousa-Becquerel/conv-agent.git ~/conv_agent
   cd ~/conv_agent
   ```

3. Copy the env template and fill it in:
   ```bash
   cp deploy/.env.production.example .env
   # edit .env — set OPENAI_API_KEY, POSTGRES_PASSWORD, JWT_SECRET
   chmod 600 .env
   ```

4. Copy the corpus PDFs into `./sample/`. From your workstation:
   ```bash
   scp -i ~/Downloads/SI_dev.pem \
     path/to/*.pdf \
     ec2-user@13.63.241.80:/home/ec2-user/conv_agent/sample/
   ```

5. Bring up postgres + qdrant + api + frontend:
   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```

   The api container runs `alembic upgrade head` on startup, so the DB
   is ready as soon as the container is healthy.

6. Index the corpus (one-shot; re-run whenever the corpus changes):
   ```bash
   docker compose -f docker-compose.prod.yml --profile indexer \
     run --rm indexer python index.py
   ```

7. Seed the first admin:
   ```bash
   docker compose -f docker-compose.prod.yml exec api \
     python -m scripts.create_user --email you@yourdomain.com --admin
   ```

## Caddy route (one-time — add to the shared Caddyfile)

`sinergia` already lives at `/sinergia/*` in the existing Caddyfile.
Add a mirror block for conv-agent inside the same
`dev.solarintelligence.ai` site block, above the catch-all
`reverse_proxy react-frontend:80`:

```caddy
handle_path /conv-agent/* {
    reverse_proxy conv-agent-frontend:80
}
```

Then:
```bash
docker exec solar-intelligence-caddy-1 caddy reload \
    --config /etc/caddy/Caddyfile
```

## Regular deploys

Push to `main`, then on the EC2:
```bash
cd ~/conv_agent
git pull --ff-only
docker compose -f docker-compose.prod.yml up -d --build
```

## Ops

**Logs:**
```bash
docker compose -f docker-compose.prod.yml logs -f api
docker compose -f docker-compose.prod.yml logs -f qdrant
```

**Backups:**
```bash
# Postgres
docker compose -f docker-compose.prod.yml exec -T postgres \
    pg_dump -U conv_agent conv_agent | gzip > \
    ~/backups/conv-agent-$(date +%F).sql.gz

# Qdrant (snapshot)
docker compose -f docker-compose.prod.yml exec qdrant \
    curl -sS -X POST http://localhost:6333/collections/conv_agent_chunks/snapshots
```

**Rotate JWT_SECRET** (invalidates every session):
Edit `.env`, then `docker compose -f docker-compose.prod.yml up -d api`.
