# 11 — Caching

All caching is Redis-backed ([`backend/db/redis.py`](../backend/db/redis.py)).
The guiding principle: **cache the expensive, deterministic intermediate steps;
never cache the final answer.**

## What is cached

| Cache | Key | TTL | Set/Read by | Why it's safe to cache |
|-------|-----|-----|-------------|------------------------|
| **Route classification** | `route:<sha256(ws+question)>` | 24h (`CACHE_TTL_ROUTE`) | [`router.py`](../backend/core/router.py) | A question's *type* (graph/vector/hybrid) is stable; it doesn't depend on the data. |
| **Cypher result set** | `cypher:<sha256(cypher)>` | 5 min (`CACHE_TTL_CYPHER`) | [`graph_retriever.py`](../backend/core/graph_retriever.py) | The graph changes slowly; 5 min bounds staleness. Keyed on the generated query text. |
| **Question embedding** | `embed:<sha256(text)>` | 7 days (`CACHE_TTL_EMBED`) | [`vector_retriever.py`](../backend/core/vector_retriever.py) | The same text always embeds to the same vector — fully deterministic. Stored as base64 float32. |

## What is NOT cached — and why

**The final synthesized answer.**
[`qa_pipeline.answer_question`](../backend/core/qa_pipeline.py) always recomputes
it (it only bumps a cache-miss counter). A cached answer captured *before* a
newly-added source finished ingesting would silently omit that source's content,
making the engine look like it doesn't know data it actually holds. Freshness of
the answer is worth the synthesis cost.

The legacy `qa:<hash>` answer-cache helpers (`get_cached_answer` /
`set_cached_answer`) still exist and `CACHE_TTL_ANSWERS` is still defined, but
**nothing writes them** in the current read path. `qa:*` keys are swept
defensively on invalidation so any entry written before answer-caching was
disabled can't be served stale.

## Invalidation

`invalidate_workspace_caches(workspace_id)` deletes `route:*`, `cypher:*`, and
`qa:*` keys. It runs after:

- a **successful ingestion** ([`jobs.py`](../backend/ingestion/jobs.py)) — new
  data may change routes and query results;
- a **source deletion** and the **cleanup sweep**
  ([`sources.py`](../backend/api/routes/sources.py)) — removed data may have been
  referenced by cached routes/queries.

It uses **`SCAN`** (cursor-based, `count=200`), not `KEYS`, so it never blocks
Redis on a large keyspace. Note the patterns are global (`route:*`), not scoped
per-workspace, because the key is a hash — invalidation is conservative (clears
all workspaces' route/cypher caches), which is correct if slightly broad.

## Other Redis state (not caches, but worth knowing)

These share Redis but are operational state, not read-path caches:

| Key | TTL | Purpose | Docs |
|-----|-----|---------|------|
| `resolver:<ws>:<type>` | 30 days | Entity-resolver embeddings for cross-source dedup. | [Ingestion → Entity resolution](06-ingestion-pipeline.md#entity-resolution-cross-source-dedup) |
| `checkpoint:<source_id>` | 7 days | Last processed document URL, for crash-resume. | [Ingestion → DLQ/checkpointing](06-ingestion-pipeline.md#concurrency-retries-dead-letter-queue) |
| `inflight:<hash>` | 60s | In-flight request dedup lock (helpers present; see `acquire_inflight_lock`). | — |
| RQ queues | — | `ingestion`, `ingestion_bulk`, `ingestion_dlq`. | [Architecture](02-architecture.md) |

## Cache observability

Hits/misses are counted per cache via Prometheus counters
`cache_hits_total{cache=…}` / `cache_misses_total{cache=…}` (labels: `route`,
`cypher`, `embedding`, `answer`). See [Observability](12-resilience-observability.md).
The `answer` cache only ever records **misses** by design.

## Tuning

All TTLs are env vars (see [Configuration](04-configuration.md)):
`CACHE_TTL_ROUTE`, `CACHE_TTL_CYPHER`, `CACHE_TTL_EMBED`, `CACHE_TTL_ANSWERS`.
Redis itself runs with `maxmemory 256mb` and `allkeys-lru` eviction
(`docker-compose.yml`), so under memory pressure the least-recently-used cache
entries are evicted first — appropriate for a cache, and the checkpoints/resolver
keys are short-lived/regenerable enough to tolerate it.

Continue to [Resilience & observability](12-resilience-observability.md).
