# 04 — Configuration

All configuration is environment variables (loaded from `.env` via
`python-dotenv`) plus Docker Compose profiles. There is no separate config file.

## Environment variables

### Required

| Variable | Example | Used by | Notes |
|----------|---------|---------|-------|
| `GEMINI_API_KEY` | `AIza…` | [`llm_client.py`](../backend/core/llm_client.py) | The only value you must set. Without it every LLM call fails. |

### Datastores (defaults match Docker Compose)

| Variable | Default | Used by |
|----------|---------|---------|
| `NEO4J_URI` | `bolt://localhost:7687` | [`neo4j.py`](../backend/db/neo4j.py) |
| `NEO4J_USER` | `neo4j` | Neo4j auth |
| `NEO4J_PASSWORD` | `kgre_dev_password` | Neo4j auth |
| `POSTGRES_USER` | `kgre` | Postgres container |
| `POSTGRES_PASSWORD` | `kgre_dev_password` | Postgres container |
| `POSTGRES_DB` | `kgre` | Postgres container |
| `POSTGRES_URL` | `postgresql://kgre:kgre_dev_password@localhost:5432/kgre` | [`postgres.py`](../backend/db/postgres.py) — async engine derives `postgresql+asyncpg://` from this |
| `REDIS_URL` | `redis://localhost:6379` | [`redis.py`](../backend/db/redis.py), [`queue.py`](../backend/db/queue.py) |
| `CHROMA_PERSIST_DIR` | `./chroma_data` | [`chroma.py`](../backend/db/chroma.py) — on-disk persistence dir |

> **Inside containers** the worker/coordinator override these to the
> service-network hostnames (`neo4j`, `postgres`, `redis`) — see the
> `environment:` blocks in [`docker-compose.yml`](../docker-compose.yml). The
> host-side `.env` uses `localhost`.

### LLM

| Variable | Default | Used by | Notes |
|----------|---------|---------|-------|
| `LLM_MODEL` | `gemini-flash-lite-latest` | `llm_client.py` | The Gemini model for all text/JSON/stream/OCR calls. |
| `LLM_CALL_TIMEOUT` | `90` (s) | `llm_client.py` | Hard ceiling on a single text/JSON Gemini call. The SDK has no built-in timeout; without this a hung call wedges an LLM thread, then extraction, then strands the source at `running`. |
| `LLM_OCR_TIMEOUT` | `180` (s) | `llm_client.py` | Longer ceiling for multimodal PDF OCR. |

### Cache TTLs (seconds)

| Variable | Default | Caches |
|----------|---------|--------|
| `CACHE_TTL_ANSWERS` | `3600` | Answer cache **(present but disabled — see note)** |
| `CACHE_TTL_ROUTE` | `86400` | Route classification (24h) |
| `CACHE_TTL_CYPHER` | `300` | Cypher result sets (5 min) |
| `CACHE_TTL_EMBED` | `604800` | Question embeddings (7 days) |

> **Answers are intentionally never cached.** A cached answer taken before a new
> source finishes ingesting would silently omit that source's content. The TTL
> constant exists and `qa:*` keys are swept on invalidation, but the read path
> always recomputes the final answer. See [Caching](11-caching.md).

### Logging

| Variable | Default | Notes |
|----------|---------|-------|
| `LOG_LEVEL` | `INFO` | structlog level. Logs are JSON. |
| `ENV` | `development` | Reported in the `startup_complete` log line. |

### Phase 3 — distributed worker pool (opt-in)

| Variable | Default | Used by |
|----------|---------|---------|
| `COORDINATOR_HOST` | `coordinator` (in-container) / `localhost` | [`worker_client.py`](../backend/coordinator/worker_client.py) |
| `COORDINATOR_PORT` | `50051` | coordinator server + worker client |
| `COORDINATOR_HEARTBEAT_SECS` | `5` | how often workers heartbeat |
| `COORDINATOR_HEARTBEAT_TIMEOUT` | `30` (s) | silence after which a worker is declared dead |
| `COORDINATOR_REAP_INTERVAL` | `5` (s) | how often the reaper runs |

### Phase 4 — sharded knowledge graph (opt-in)

| Variable | Default | Used by |
|----------|---------|---------|
| `USE_SHARDING` | `false` | [`shard_router.is_enabled()`](../backend/db/shard_router.py) — master switch |
| `NUM_SHARDS` | `3` | `shard_router.num_shards()` — **do not change after data is written** |
| `NEO4J_SHARD_0_URI` | `bolt://localhost:7687` | shard 0 (defaults to base ports `7687+i` if unset) |
| `NEO4J_SHARD_1_URI` | `bolt://localhost:7688` | shard 1 |
| `NEO4J_SHARD_2_URI` | `bolt://localhost:7689` | shard 2 |

`USE_SHARDING=true` makes the ingestion worker and graph reads route through the
shard router instead of the single-node driver. See [Sharding](10-sharding.md).

## Docker Compose profiles

[`docker-compose.yml`](../docker-compose.yml) defines services gated by
profiles, so the **default** `docker compose up` brings only the three core
stores online.

| Profile | Services added | Command | When |
|---------|----------------|---------|------|
| *(none / default)* | `neo4j`, `postgres`, `redis` | `docker compose up -d neo4j postgres redis` | Always — local dev. |
| `sharding` | `neo4j-1` (`:7688`), `neo4j-2` (`:7689`) | `docker compose --profile sharding up -d` | Phase 4. Set `USE_SHARDING=true`, `NUM_SHARDS=3`. |
| `production` | `worker` (RQ worker container) | `docker compose --profile production up` | Run the worker as a container instead of via `dev.ps1`. |
| `distributed` | `coordinator` (`:50051`), `dworker` | `docker compose --profile distributed up -d --scale dworker=3` | Phase 3. Replaces the single RQ worker with the gRPC pool. |

### Ports

| Container | Host port(s) | Purpose |
|-----------|--------------|---------|
| `kgre-neo4j` (shard 0) | 7474 (HTTP), 7687 (Bolt) | Graph + browser UI |
| `kgre-neo4j-1` (shard 1) | 7475, 7688 | Phase 4 only |
| `kgre-neo4j-2` (shard 2) | 7476, 7689 | Phase 4 only |
| `kgre-postgres` | 5432 | Product data |
| `kgre-redis` | 6379 | Cache + queue |
| `kgre-coordinator` | 50051 | gRPC, Phase 3 only |

### Resource limits & health

Each container declares memory limits (Neo4j 2g, Postgres 512m, Redis 384m,
workers 1g) and Neo4j/Postgres/Redis declare healthchecks; the `production`
worker waits on those healthchecks via `depends_on … condition: service_healthy`.
Redis is configured with `--maxmemory 256mb --maxmemory-policy allkeys-lru` and
60s/1-key snapshotting.

## Frontend configuration

The frontend reads two optional Vite env vars:

| Variable | Default | Effect |
|----------|---------|--------|
| `VITE_API_URL` | `""` (same-origin) | Base URL for the axios client; leave empty to use the Vite `/api` proxy. Set to bypass the proxy and hit a backend directly. |
| `VITE_PROXY_TARGET` | `http://127.0.0.1:8000` | Where the Vite dev-server proxy forwards `/api/*`. |

See [`vite.config.ts`](../frontend/vite.config.ts) and [Frontend](13-frontend.md).

Continue to [Data models](05-data-models.md).
