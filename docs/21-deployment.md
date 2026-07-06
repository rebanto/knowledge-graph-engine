# Phase 7 Deployment: Hugging Face Docker Space

Phase 7 is the card-free production path: one public Hugging Face Docker Space
on free `cpu-basic` hardware, with external free managed state in Neo4j AuraDB
Free and Neon Postgres Free. Do not add AWS/OCI SDKs or cloud-specific runtime
code for this deployment.

Share the direct Space URL:

```text
https://<user>-<space>.hf.space
```

Do not share the embedded `huggingface.co/spaces/...` iframe view for normal
use. Browser cookies are unreliable there, and this app uses HttpOnly cookies
for auth and EventSource.

## Architecture

| Component | Free target | Notes |
|-----------|-------------|-------|
| App runtime | Hugging Face Docker Space, `cpu-basic` | 2 vCPU, 16 GB RAM, one HTTP port, HTTPS provided, sleeps after inactivity |
| API + frontend | One container | FastAPI serves the built React app and `/api/*` |
| Worker | Same container | Single RQ worker, not the distributed coordinator pool |
| Redis | Same container | Localhost only; cache/queue reset on restart |
| ChromaDB server | Same container | Server mode on localhost; data restored from/uploaded to a Dataset snapshot |
| Graph | Neo4j AuraDB Free | `neo4j+s://...`; Aura may pause after 72h idle |
| Relational DB | Neon Postgres Free | Use pooled URL with `sslmode=require` |

Production uses:

```dotenv
USE_SHARDING=false
USE_RERANKER=true
REDIS_URL=redis://127.0.0.1:6379
CHROMA_HOST=127.0.0.1
CHROMA_PORT=8001
```

The coordinator/sharded layers remain local opt-ins. The Phase-4 benchmark
showed single-node graph latency is the right trade-off at this scale.

## Account Setup

1. Hugging Face:
   - Create a Hugging Face account.
   - Create a new Space with SDK `Docker`, hardware `cpu-basic`, visibility
     public, and app port `7860`.
   - Create a private Dataset repo for Chroma snapshots, for example
     `<user>/kgre-chroma-backup`.
   - Create an HF write token. Store it as `HF_TOKEN` in the Space secrets.
2. Neo4j AuraDB Free:
   - Create a free AuraDB instance and copy its `neo4j+s://...` URI, username,
     and password.
   - Aura Free may pause after 72 hours without queries. It is deleted only
     after 90 days paused; resume it from the Aura console.
3. Neon:
   - Create a free Postgres project.
   - Use the pooled connection string with `sslmode=require`.

## Space Variables

Copy `.env.space.example` into the Space settings as variables/secrets. Required:

```dotenv
GEMINI_API_KEY=
AUTH_SECRET_KEY=
NEO4J_URI=neo4j+s://<id>.databases.neo4j.io
NEO4J_USER=neo4j
NEO4J_PASSWORD=
POSTGRES_URL=postgresql://...?...sslmode=require
REDIS_URL=redis://127.0.0.1:6379
CHROMA_HOST=127.0.0.1
CHROMA_PORT=8001
HF_TOKEN=
CHROMA_BACKUP_REPO=<user>/kgre-chroma-backup
FRONTEND_ORIGIN=https://<user>-<space>.hf.space
COOKIE_SECURE=true
REGISTRATION_ENABLED=true
USE_RERANKER=true
USE_SHARDING=false
ALLOW_PRIVATE_SOURCE_URLS=false
RATE_LIMIT_ENABLED=true
BOOTSTRAP_DEMO=arxiv_seed
```

`ALLOW_PRIVATE_SOURCE_URLS=false` protects user-supplied `rss` and `web_url`
sources. It does not block internal Redis/Chroma localhost connections, and it
does not apply to ArXiv category strings used by the demo bootstrap.

## Deploy

Set `HF_TOKEN` locally and push the current branch to the Space:

```bash
export HF_TOKEN=hf_...
scripts/deploy_hf.sh <user>/<space>
```

PowerShell:

```powershell
$env:HF_TOKEN = "hf_..."
.\scripts\deploy_hf.ps1 <user>/<space>
```

Use `--force` / `-Force` only when the Space branch should be replaced by the
current local branch:

```bash
scripts/deploy_hf.sh <user>/<space> --force
```

Secrets come from Space settings. `.env` files are excluded and should not be
pushed.

## Keepalive

The repo includes `.github/workflows/keepalive.yml`, scheduled every 6 hours.
Set a repository variable:

```text
KEEPALIVE_URL=https://<user>-<space>.hf.space/api/keepalive
```

The endpoint runs `SELECT 1` against Postgres and `RETURN 1` against Neo4j. A
non-200 response makes the GitHub Actions run red so you notice dependency or
resume issues.

## Demo Bootstrap

With `BOOTSTRAP_DEMO=arxiv_seed`, the first startup creates a public NULL-owner
workspace `arxiv_seed`, adds the default ArXiv feed
`cs.AI,cs.LG,cs.CL`, and enqueues ingestion through the normal RQ path. Later
boots do not duplicate the workspace or source. If the Space restarted before
ingestion finished and Redis lost the queue, startup re-enqueues the pending demo
source.

## Ephemeral Disk

The Space container disk is ephemeral.

- ChromaDB is restored from the latest private Dataset snapshot before Chroma
  starts.
- ChromaDB is backed up after successful ingestion, debounced, and again on a
  24-hour timer from the supervisor.
- Redis cache and RQ queue reset on restart. This is acceptable; sources and
  reports live in Postgres, and Chroma can restore from the latest snapshot.
- Uploaded PDF originals are not retained after a container restart. Their
  extracted graph/vector data remains if ingestion completed and Chroma was
  snapshotted.

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Space build fails | Open Space build logs; confirm Docker SDK, app port 7860, and that `requirements.txt` installed |
| App starts but UI is blank | Confirm `STATIC_DIR=/app/frontend_dist` and visit the direct `.hf.space` URL |
| Login/cookies fail | Do not use the Hugging Face iframe; confirm `COOKIE_SECURE=true` and `FRONTEND_ORIGIN` matches the direct URL |
| Keepalive red | Open `/api/keepalive`; Aura may need console resume, Neon may be cold, or secrets may be wrong |
| Vector answers missing after restart | Check logs for Chroma restore/backup and verify `CHROMA_BACKUP_REPO` points to the private Dataset |
| Sources stuck pending | Redis queue is ephemeral; re-add/retry the source if the Space restarted before a worker picked it up |

## Cost Table

| Item | Tier | Cash cost |
|------|------|-----------|
| Hugging Face Space | Docker `cpu-basic` | $0 |
| Neo4j AuraDB | Free | $0 |
| Neon Postgres | Free | $0 |
| Hugging Face Dataset backup | Private dataset for Chroma snapshot | $0 within free account limits |
| GitHub Actions keepalive | Public/private repo included minutes vary | $0 for normal light cron usage |
