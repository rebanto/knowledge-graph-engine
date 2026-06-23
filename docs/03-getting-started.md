# 03 — Getting started

## Prerequisites

- **Docker Desktop** (running) — for Neo4j, PostgreSQL, Redis.
- **Python 3.11+** — the backend and worker.
- **Node 18+** with **npm** or **pnpm** — the frontend. (`dev.ps1` prefers pnpm
  when `frontend/pnpm-lock.yaml` is present.)
- A **Gemini API key** (`GEMINI_API_KEY`). The free tier works but is rate- and
  quota-limited; see [Rate limits & quota](#rate-limits--quota).

The repo targets **Windows + PowerShell** (there is a `dev.ps1` orchestration
script). The application code is cross-platform; only the convenience launcher
is PowerShell-specific.

## 1. Configure `.env`

Copy the template and fill in your key:

```powershell
Copy-Item .env.example .env
# then edit .env and set GEMINI_API_KEY=...
```

`dev.ps1` does this copy automatically on first run and warns if the key is
missing. Every variable is documented in [Configuration](04-configuration.md).
The defaults (Neo4j/Postgres/Redis URIs and passwords) match the Docker Compose
services, so usually the **only** value you must set is `GEMINI_API_KEY`.

## 2. Start everything (one command)

```powershell
.\dev.ps1
```

What it does, in order ([`dev.ps1`](../dev.ps1)):

1. Checks `python`, `node`, `docker` are present and Docker is running.
2. Ensures `.env` exists (copies from `.env.example` if not).
3. **Starts Docker infra first** (`neo4j postgres redis`) so Neo4j's ~30–45s
   boot overlaps with dependency installation.
4. Creates `.venv` if missing and installs Python deps — **only when
   `requirements.txt` changed** (SHA-256 hash-cached in `.dev-cache/`).
5. Installs frontend deps the same way (hash-cached).
6. Waits for Neo4j/Postgres/Redis TCP ports to open (fast probe, 120s timeout).
7. Clears any stale processes on :8000 / :5173 and the old worker.
8. Launches three terminal windows: **backend** (uvicorn :8000), **RQ worker**,
   **frontend** (vite :5173).
9. Polls `http://127.0.0.1:8000/health/live` and only prints **"ready"** once the
   backend actually answers (so the UI won't flash a connection error).

Useful flags:

| Command | Effect |
|---------|--------|
| `.\dev.ps1` | Normal start; installs deps only if a lockfile changed. |
| `.\dev.ps1 -SkipDeps` | Fastest start; assume deps are current. |
| `.\dev.ps1 -Force` | Force a dependency reinstall. |
| `.\dev.ps1 -Stop` | Stop the three dev processes **and** the Docker infra. |

When it's up:

| URL | What |
|-----|------|
| http://localhost:5173 | The app |
| http://localhost:8000 | The API |
| http://localhost:8000/docs | FastAPI interactive docs (OpenAPI) |
| http://localhost:8000/health/ready | Dependency readiness probe |
| http://localhost:7474 | Neo4j Browser (user `neo4j`, password from `.env`) |

## Manual startup (without `dev.ps1`)

If you're not on Windows or want explicit control:

```bash
# 1. infra
docker compose up -d neo4j postgres redis

# 2. python deps
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3. backend (terminal A)
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000

# 4. RQ worker (terminal B)
python scripts/ingestion_worker.py

# 5. frontend (terminal C)
cd frontend && npm install && npm run dev
```

The backend's **lifespan** ([`main.py`](../backend/main.py)) runs DB table
creation, safe column migrations, the default-workspace seed, and crashed-worker
recovery on startup — there is no separate migration step to run.

## 3. Get data into the graph

You have two options.

### Option A — seed from the command line (fastest first graph)

[`scripts/seed_arxiv.py`](../scripts/seed_arxiv.py) populates Neo4j and ChromaDB
directly, **without** the RQ worker, and marks the `arxiv_seed` workspace's
source as `success`:

```powershell
python scripts/seed_arxiv.py --max 500 --days 90
```

It rate-limits itself to ~1 LLM call / 7s to respect the free Gemini tier, and
stops cleanly if it hits the daily quota (resume the next day). See
[Scripts](14-scripts.md#seed_arxivpy).

### Option B — add a source in the UI

1. Open http://localhost:5173.
2. Pick (or create) a workspace.
3. In the Sources panel, add a source. For an **ArXiv** source the URL field
   accepts category codes (`cs.AI`), paper IDs (`2401.12345`), arxiv.org URLs,
   or free-text search. You can also add an RSS feed, a web URL, or upload a PDF.
4. The source is enqueued to the RQ worker; the source card shows live status
   (`pending → running → success`). Ask questions once it's `success`.

A workspace with a **description** can also **auto-discover** ArXiv categories
(`POST /workspaces/{id}/discover`, surfaced in the UI) — Gemini maps the
description to 2–4 category slugs.

## 4. Ask a question

In the UI, type a question and submit. The frontend uses the **SSE streaming
endpoint** (`GET /api/question/stream`) so you see progress events ("Analyzing
question…", "Querying knowledge graph…", "Synthesizing answer…") and then the
final answer with insight cards. If streaming fails it falls back to a plain
`POST /api/question`.

From the CLI:

```powershell
python scripts/ask.py "How is attention related to transformers?"
```

## Rate limits & quota

The default model is `gemini-flash-lite-latest` on the **free tier**:

- **Per-minute (RPM)** limits: ingestion fans out several extraction windows per
  document concurrently (bounded to 4), so bursts of `429`/`503` are normal and
  absorbed by the per-call retry loop — they do **not** trip the circuit breaker
  (deliberately; see [Resilience](12-resilience-observability.md)).
- **Per-day (RPD)** quota: when exhausted, Gemini returns a `PerDay` error which
  surfaces as `DailyQuotaExhausted` → **HTTP 503** with `Retry-After: 86400`.
  The seed script stops; the API returns a clear message. Resume after reset.

If you hit quota constantly, set a different `LLM_MODEL` in `.env`.

## Quick verification

```bash
curl http://localhost:8000/health/ready          # all three stores "ok"
curl http://localhost:8000/api/system/queue       # RQ worker present + queue depths
curl "http://localhost:8000/api/graph?workspace_id=arxiv_seed&limit=50"  # nodes+edges
```

In Neo4j Browser (http://localhost:7474):

```cypher
MATCH (n) RETURN labels(n)[0] AS type, count(*) ORDER BY count(*) DESC;
MATCH ()-[r]->() RETURN type(r), count(*) ORDER BY count(*) DESC;
```

Continue to [Configuration](04-configuration.md).
