# 02 — Architecture

## Component map

```
                          ┌───────────────────────────┐
                          │      Frontend (Vite)       │
                          │   React + TS SPA :5173     │
                          └─────────────┬─────────────┘
                                        │  /api/*  (Vite proxy → :8000)
                          ┌─────────────▼─────────────┐
                          │     FastAPI app :8000      │
                          │   backend/main.py          │
                          │  ┌──────────────────────┐  │
                          │  │ routes: questions,    │  │
                          │  │ workspaces, sources,  │  │
                          │  │ graph, system         │  │
                          │  └──────────────────────┘  │
                          └──┬───────────┬──────────┬──┘
              read path      │           │ write    │ enqueue
        ┌────────────────────┘           │ (graph/  │ (RQ)
        │                                 │  vector) │
   ┌────▼─────┐  ┌──────────┐  ┌──────────▼──┐  ┌────▼──────────┐
   │  Router  │  │  Redis   │  │  Neo4j      │  │ RQ ingestion   │
   │ (Gemini) │  │  cache + │  │  (graph)    │  │ worker         │
   └────┬─────┘  │  queue   │  └─────────────┘  │ (SimpleWorker) │
        │        └────┬─────┘  ┌─────────────┐  └────┬───────────┘
   ┌────▼──────┐      │        │  ChromaDB   │       │ fetch→chunk→
   │ graph_    │      │        │  (vectors,  │       │ extract→write
   │ retriever │      │        │ in-process) │       │
   │ vector_   │      │        └─────────────┘       │
   │ retriever │   ┌──▼──────────┐                   │
   └────┬──────┘   │ PostgreSQL  │◄──────────────────┘
        │          │ (product    │   jobs, sources,
   ┌────▼──────┐   │  data)      │   workspaces, reports
   │ Synthesizer│  └─────────────┘
   │ (Gemini)   │
   └────────────┘
```

Everything runs locally. The four stores (Neo4j, PostgreSQL, Redis, ChromaDB)
plus the LLM (Gemini, remote) are the only external dependencies.

- **Neo4j, PostgreSQL, Redis** run as Docker containers (`docker-compose.yml`).
- **ChromaDB** runs **in-process** inside whatever Python process touches it
  (the API server for reads, the worker for writes), persisting to
  `CHROMA_PERSIST_DIR` (`./chroma_data`). It is *not* a container.
- **Gemini** is a remote HTTP API reached through the `google-genai` SDK.

## Process model (default / local dev)

`dev.ps1` launches three local processes plus the Docker infra:

| Process | Command | Port | Role |
|---------|---------|------|------|
| Backend | `uvicorn backend.main:app --reload` | 8000 | FastAPI: serves the API, reads graph+vectors, runs the query pipeline |
| Worker | `python scripts/ingestion_worker.py` | — | RQ `SimpleWorker` draining the `ingestion` / `ingestion_bulk` queues |
| Frontend | `vite` | 5173 | React dev server, proxies `/api` to :8000 |
| Infra | `docker compose up neo4j postgres redis` | 7474/7687, 5432, 6379 | The three stores |

The **RQ worker is a separate process from the API** and communicates only
through Redis (the queue) and the shared databases. This is the key reason the
event-loop-disposal discipline matters (see below).

### Why `SimpleWorker`, and the event-loop discipline

RQ's default `Worker` uses `os.fork()`, which does not exist on Windows, so the
worker uses **`SimpleWorker`** which runs each job in-process. Each job is
executed via a fresh `asyncio.run(...)` — a **new event loop per job**.

The module-global async pools (SQLAlchemy async engine, Neo4j async driver,
redis.asyncio client, shard router) bind their connection pools to the loop that
first created them. If they aren't disposed before that loop closes, the *next*
job's loop inherits stale pools and dies with `RuntimeError: Event loop is
closed`. Therefore every job runs inside
[`_run_and_cleanup`](../backend/ingestion/jobs.py) which disposes **all** global
async pools in a `finally`. This is load-bearing; see
[Ingestion → Event-loop disposal](06-ingestion-pipeline.md#the-event-loop-disposal-rule).

## The two retrieval systems

### System 1 — Knowledge Graph (Neo4j)

- **Nodes:** `Person`, `Organization`, `Paper`, `Concept`, `Event`, `Topic`.
- **Edges:** authorship/citation (`AUTHORED`, `CITED`, `COLLABORATED_WITH`),
  affiliation/funding (`AFFILIATED_WITH`, `FUNDED_BY`), conceptual structure
  (`MENTIONS`, `ABOUT`, `USES`, `PROPOSES`, `EXTENDS`, `IMPROVES`,
  `COMPARED_TO`, `EVALUATED_ON`, `APPLIED_TO`, `PART_OF`, `RELATED_TO`,
  `PUBLISHED_IN`, `PRESENTED_AT`), and claims (`SUPPORTS`, `CONTRADICTS`,
  `CONFLICTS_WITH`).
- Queried in **Cypher**, generated by Gemini from the question, validated for
  read-only safety, executed against Neo4j (or the shard router under Phase 4).
- Good for "how is X connected to Y", citation chains, "who collaborated",
  "most cited", contradiction detection.

### System 2 — Vector Search (ChromaDB)

- One collection per workspace: `workspace_{workspace_id}_chunks`, cosine space.
- Documents chunked (~400 words / ~512 tokens, 40-word overlap), embedded with
  the local `all-MiniLM-L6-v2` sentence-transformer, upserted with deterministic
  IDs `{workspace_id}:{source_url}:{chunk_index}`.
- At query time the question is embedded (with a Redis embedding cache) and the
  nearest chunks are retrieved with their source metadata.
- Good for "summarize findings on…", "what does research say about…", "open
  problems in…".

### The Router

[`router.py`](../backend/core/router.py) — a Gemini classifier returning
`{type, reasoning}`. Result cached in Redis for 24h. Invalid/unknown types fall
back to `hybrid`.

Full read-path detail: [Query pipeline](07-query-pipeline.md).

## Read path vs. write path

The system has two largely independent paths that share the stores:

- **Write path (ingestion):** `source → fetch → chunk → (embed→Chroma ∥
  extract→Neo4j) → mark job done`. Runs in the RQ worker (default) or the
  distributed worker pool (Phase 3). Detailed in
  [Ingestion pipeline](06-ingestion-pipeline.md).
- **Read path (query):** `question → route → retrieve (graph ∥ vector) →
  synthesize → save report`. Runs in the API process. Detailed in
  [Query pipeline](07-query-pipeline.md).

The two paths never call each other directly; they coordinate only through the
shared Neo4j/Chroma/Postgres/Redis state and through cache invalidation (a
finished ingestion clears the route and Cypher caches for the workspace).

## Optional layers (opt-in)

These are fully implemented but **off by default**. The system runs single-node,
single-worker unless you turn them on.

| Layer | Phase | How to enable | Docs |
|-------|-------|---------------|------|
| Distributed worker pool (gRPC coordinator + N workers) | 3 | `docker compose --profile distributed up` | [09](09-distributed-workers.md) |
| Sharded Neo4j (consistent-hash router, 2–3 shards) | 4 | `USE_SHARDING=true` + `--profile sharding` | [10](10-sharding.md) |
| Production RQ worker container | — | `--profile production` | [Configuration](04-configuration.md) |

The ingestion `process_document` code is **identical** whether it writes to a
single Neo4j or through the shard router — [`worker._graph()`](../backend/ingestion/worker.py)
picks the backend at runtime, and both expose the same
`merge_node / merge_edge / merge_paper / mark_paper_processed` surface.

## Repository layout

```
backend/
  main.py                     FastAPI app: lifespan (migrations + recovery), middleware, health, /metrics
  api/routes/
    questions.py              POST /question, GET /question/stream (SSE), reports CRUD
    workspaces.py             workspace CRUD + source auto-discovery
    sources.py                source CRUD, upload, retry, re-ingest, delete, cleanup
    graph.py                  GET /graph (visualization data)
    system.py                 GET /system/queue (RQ worker + queue health)
  core/
    router.py                 question → graph|vector|hybrid (Gemini)
    graph_retriever.py        question → Cypher → Neo4j (+ entity-degree context)
    vector_retriever.py       question → embedding → ChromaDB
    synthesizer.py            retrieved data → prose + insight cards (Gemini)
    qa_pipeline.py            orchestrates route → retrieve → synthesize
    llm_client.py             the Gemini client (json/text/stream/OCR), bulkhead, timeouts
    graph_explorer.py         hub-centred subgraph for the GraphViewer
    source_discovery.py       workspace description → ArXiv categories (Gemini)
    resilience.py             circuit breakers + retry decorator
    observability.py          structlog config, Prometheus metrics, request-id middleware
  ingestion/
    dispatcher.py             routes a source to its fetcher
    fetchers/{arxiv,rss,web,pdf}.py
    chunker.py                word-window chunking
    entity_extractor.py       windowed LLM extraction + merge/dedup
    entity_resolver.py        cross-source dedup via embedding cosine similarity
    conflict_detector.py      SUPPORTS/CONTRADICTS conflict flagging
    worker.py                 process_document: the per-document pipeline
    jobs.py                   RQ entry point + event-loop disposal + DLQ
  coordinator/                Phase 3 distributed worker pool
    server.py                 gRPC server + dead-worker reaper
    registry.py               in-memory worker/batch registry (unit-testable)
    scheduler.py              pulls pending sources → coordinator pending pool
    worker_client.py          worker-side gRPC client
    coordinator_pb2*.py       generated gRPC stubs
  db/
    postgres.py               sync + async SQLAlchemy engines
    models.py                 Workspace, Report, Source, IngestionJob
    neo4j.py                  single-node driver + merge/remove/count helpers
    shard_router.py           Phase 4 consistent-hash router
    chroma.py                 ChromaDB client + embedding (sentence-transformers)
    redis.py                  caches, checkpoints, resolver registry, sync client for RQ
    queue.py                  RQ queue accessors (ingestion / ingestion_bulk / ingestion_dlq)
  models/schemas.py           Pydantic request/response models

frontend/src/
  App.tsx                     top-level layout + state
  api.ts                      typed axios client + SSE helper
  types.ts                    shared TS types
  components/                 QuestionInput, AnswerView, InsightCards, GraphViewer,
                              Sidebar, SourceManager, SourcesPanel, WorkspaceSelector,
                              EntitySummary, RoutingBadge, EmptyState, ErrorBoundary

proto/coordinator.proto       gRPC service: Register, RequestWork, Heartbeat, ReportCompletion

scripts/
  seed_arxiv.py               one-time graph seed (no worker needed)
  benchmark_sharding.py       single-node vs sharded latency
  coordinator_test.py         registry/reassignment test
  shard_router_test.py        shard routing + scatter-gather test
  sharded_ingest_test.py      end-to-end sharded ingestion
  e2e_source_test.py          end-to-end source ingestion
  detect_conflicts.py         retroactive conflict pass
  ask.py                      CLI question runner
  repro_event_loop_disposal.py  regression repro for the loop-disposal bug
  test_gemini.py              Gemini connectivity smoke test
  ingestion_worker.py         the RQ SimpleWorker entry point
```

Continue to [Getting started](03-getting-started.md).
