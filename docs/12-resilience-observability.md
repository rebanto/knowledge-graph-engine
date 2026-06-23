# 12 — Resilience & observability

## Resilience patterns

[`backend/core/resilience.py`](../backend/core/resilience.py) plus targeted
patterns in the LLM client and ingestion job.

### Circuit breakers (`pybreaker`)

One breaker per external dependency, shared across all requests. Opens after
`fail_max` failures, half-opens after `reset_timeout` to probe recovery.

| Breaker | `fail_max` | `reset_timeout` | Guards |
|---------|-----------|-----------------|--------|
| `gemini_breaker` | 5 | 30s | Gemini calls (checked, see caveat) |
| `neo4j_breaker` | 5 | 30s | Neo4j queries in `graph_retriever._exec` |
| `external_breaker` | 3 | 60s | External HTTP (available for fetchers) |

When a breaker is open, callers raise `CircuitBreakerError`, which the read path
catches to **degrade gracefully** (graph retrieval failing still lets vector
results through, and vice versa — see [Query pipeline](07-query-pipeline.md)).

> **Important caveat on the Gemini breaker.** The breaker is *checked* before
> each Gemini call, but the actual call is **deliberately not routed through
> it**. Entity extraction fires several windows concurrently per document, so
> transient `429`/`503` bursts arrive together; counting each toward the breaker
> would trip it open and cascade every in-flight document to failure. The
> per-call retry loop in [`llm_client._call_sync`](../backend/core/llm_client.py)
> is the right granularity for absorbing those transients. The breaker still
> protects against a sustained Gemini outage.

### Retries (`tenacity`)

- A reusable `with_retry(...)` decorator (exponential backoff + full jitter,
  works on sync and async functions) is available in `resilience.py`.
- The LLM client has its own inline retry loop for transient `ServerError`
  (2 retries, capped 10s backoff).
- The **frontend** axios client retries network errors and 5xx with exponential
  backoff (`axios-retry`, 3 retries) — so the UI survives a backend restart
  without a page reload.

### Timeouts

- **LLM:** `asyncio.wait_for` on every Gemini call (`LLM_CALL_TIMEOUT=90s`, OCR
  `180s`). The SDK has no built-in timeout; this prevents a hung call from
  wedging an LLM thread → extraction → stranding a source at `running`.
- **Neo4j:** `connection_acquisition_timeout=5s`; query exec timeout 15s
  (graph), 8s (entity-degree pass).
- **HTTP fetchers:** aiohttp client timeouts (arxiv 60s, web 20s).

### Bulkheads (thread-pool isolation)

The Gemini SDK and ChromaDB are synchronous, so they run in **dedicated thread
pools** to stop slow I/O from starving each other or the DB pools:

| Pool | Workers | In |
|------|---------|-----|
| LLM | 8 | `llm_client._llm_executor` |
| ChromaDB | 4 | `chroma._executor` |
| feedparser (arxiv) | 2 | `fetchers/arxiv.py` |
| pdf | 2 | `fetchers/pdf.py` |

### Graceful degradation & "no silent black holes"

- A failing retriever is caught; the other path still contributes.
- A source fetching 0 documents, or whose every document fails, is marked
  `error` — never a green success that answers "no information".
- A malformed LLM response can't break a response: synthesizer output is
  defensively validated and clamped; an empty structured answer falls back to a
  plain-text prompt.

### Crash recovery (see also [Operations](15-operations.md))

- **Startup** ([`main.py`](../backend/main.py)) resets any source stuck in
  `running` (its owning worker died) to `error` with a retry hint.
- **Per-request** safety nets in `list_sources` and `cleanup` reset sources
  stuck `running` past 15 minutes, without needing a backend restart.
- The **event-loop disposal** discipline in the worker prevents the
  cross-job `Event loop is closed` failure class entirely.

## Observability

[`backend/core/observability.py`](../backend/core/observability.py).

### Structured logging (`structlog`)

JSON logs at `LOG_LEVEL` (default `INFO`). Every log line includes ISO
timestamp, level, logger name, and any bound context. `RequestIDMiddleware`
binds a per-request `request_id` (from the `X-Request-ID` header or generated)
into the context, so all logs for one request are correlatable; the id is echoed
back in the response header.

### Prometheus metrics (`GET /metrics`)

| Metric | Type | Labels | Meaning |
|--------|------|--------|---------|
| `http_requests_total` | Counter | method, path, status | All HTTP requests. |
| `http_request_duration_seconds` | Histogram | path | Request latency. |
| `llm_calls_total` | Counter | operation, status | Gemini calls — `status ∈ {ok, server_error, client_error, quota, circuit_open}`, `operation ∈ {generate, ocr}`. |
| `cache_hits_total` / `cache_misses_total` | Counter | cache | Per-cache hit/miss (`route`, `cypher`, `embedding`, `answer`). |
| `ingestion_queue_depth` | Gauge | — | Jobs in the ingestion queue. |

`RequestIDMiddleware` records the HTTP request/duration metrics; the LLM client
and cache layers increment their own counters inline.

### Health checks

| Endpoint | Checks | Returns |
|----------|--------|---------|
| `GET /health/live` | process up | `{status: "ok"}` |
| `GET /health/ready` | Postgres + Redis + Neo4j reachable | `200` all-ok, else `503` with per-store `"unreachable: …"` |

`dev.ps1` polls `/health/live` before declaring the stack ready;
`/health/ready` is the dependency-aware probe for orchestration.

### Worker / queue visibility

`GET /api/system/queue` reports RQ worker state and the depth of the
`ingestion`, `ingestion_bulk`, `ingestion_dlq` queues (drives the Sources UI
worker indicator). The Phase-3 registry exposes `snapshot()` with
`pending / workers / batches / reassignments / dead_workers`.

Continue to [Frontend](13-frontend.md).
