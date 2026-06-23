# 09 — Distributed worker pool (Phase 3)

**Status: implemented, opt-in.** The default ingestion path is the single RQ
`SimpleWorker`. This layer replaces it with a **coordinator + N gRPC workers**
when you bring up the `distributed` Compose profile. The per-document pipeline
(`process_document`) is **unchanged** — only the execution/orchestration layer
differs. The simpler RQ path remains the fallback.

## Why

A single RQ worker is a single point of failure and a throughput ceiling. The
coordinator/worker model makes ingestion horizontally scalable and
fault-tolerant: workers can be added, killed, or restarted without losing work,
because reassignment + idempotent writes make a double-processed document
harmless.

## Architecture

```
                ┌──────────────────────────────────────────┐
                │            Coordinator (one process)       │
                │  scheduler ── pulls 'pending' sources →    │
                │              expands to DocRefs →          │
                │              registry.pending pool         │
                │  gRPC server (:50051):                     │
                │     Register / RequestWork /               │
                │     Heartbeat / ReportCompletion           │
                │  reaper ── every 5s: declare silent        │
                │            workers dead, requeue batches   │
                └───────┬───────────┬───────────┬───────────┘
                        │ gRPC      │           │
                 ┌──────▼───┐ ┌─────▼────┐ ┌────▼─────┐
                 │ worker-1 │ │ worker-2 │ │ worker-3 │   (docker compose --scale dworker=3)
                 └──────────┘ └──────────┘ └──────────┘
                        │           │           │
                        └─────── process_document ───────►  Neo4j + ChromaDB + Postgres
```

The gRPC contract is [`proto/coordinator.proto`](../proto/coordinator.proto);
generated stubs are `coordinator_pb2*.py`.

## Components

### Coordinator server — [`coordinator/server.py`](../backend/coordinator/server.py)

An `grpc.aio` server exposing the four RPCs (thin wrappers over the registry)
plus a background **reaper** task. Heartbeat/timeout/reap intervals are
env-configurable (`COORDINATOR_HEARTBEAT_SECS=5`, `…_TIMEOUT=30`,
`…_REAP_INTERVAL=5`). Run standalone: `python -m backend.coordinator.server`.

### Worker registry — [`coordinator/registry.py`](../backend/coordinator/registry.py)

The heart of the pool: pure data structures + an `asyncio.Lock`, **no gRPC**, so
it's unit-testable in isolation ([`scripts/coordinator_test.py`](../scripts/coordinator_test.py)).
It tracks:

- `_pending: deque[DocRef]` — documents waiting for a worker.
- `_workers: {id → Worker(state, last_seen, batch_id)}`.
- `_batches: {id → Batch(docs, worker_id, state, completed, total)}`.
- counters `reassignments`, `dead_workers` (for the failure test / dashboards).

Key methods:

| Method | Behaviour |
|--------|-----------|
| `add_documents` | Scheduler loads DocRefs into the pending pool. |
| `register` | Record a worker as alive. |
| `request_work(id, max_docs)` | Pop up to `max_docs` from pending into a new `Batch`, assign it; **auto-registers** an unknown worker so a restarted worker recovers. Returns `None` if no work. |
| `heartbeat(id, batch, status, completed, total)` | Refresh liveness; returns `keep_going=False` if this batch was taken away (worker was reaped + batch reassigned), telling the worker to drop it. |
| `complete(batch, id, succeeded, failed)` | Mark a batch done. A **late, reassigned-away worker is ignored** (the live worker's run is authoritative; duplicate work is harmless due to idempotency). |
| `reap_dead()` | Mark workers past the heartbeat timeout dead and **requeue their in-flight batch** (`extendleft`, so reassigned docs are retried promptly). |
| `snapshot()` | Observability dump. |

### Scheduler — [`coordinator/scheduler.py`](../backend/coordinator/scheduler.py)

`pull_pending_once` selects Postgres sources with `status='pending'`, expands
each via the existing `fetch_documents_for_source`, loads the resulting DocRefs
into the registry, and flips the source to `running` (so it isn't picked twice).
Zero-doc / failing fetches mark the source `error`. `run_scheduler` polls every
5s. This bridges the existing source/job data model to the pool without changing
the pipeline.

### Worker client — [`coordinator/worker_client.py`](../backend/coordinator/worker_client.py)

`WorkerClient.run()`:

1. `Register` with the coordinator; adopt its heartbeat interval.
2. Loop: `RequestWork` → if a batch comes back, process it; else idle-sleep.
3. `_process_batch`: spawn a **heartbeat loop** (every `heartbeat_secs`, sending
   `{completed, total}`); process each doc via the injected `process_fn`; on
   `keep_going=False` set `revoked` and stop; finally `ReportCompletion` with the
   succeeded/failed URL lists.

The processor is **injected** — production uses `_real_process` (fetch the
source, find the target document, run the real `process_document`); tests inject
a controllable stub. Worker id defaults to `{hostname}-{pid}`. Run standalone:
`python -m backend.coordinator.worker_client`.

## Failure recovery & idempotency

When a worker misses heartbeats past the timeout, the reaper marks it dead and
requeues its batch; a live worker picks it up. The "dead" worker may actually be
alive and finish late — creating a **double-processing window**. This is safe
because:

- **Neo4j** writes use `MERGE` (entity + relationship), so a second write
  updates rather than duplicates.
- **ChromaDB** writes use `upsert` with deterministic chunk IDs — a no-op on
  replay.
- **PostgreSQL** job records use conditional updates so a late worker can't
  overwrite a completed record.
- At the **registry** level, `complete()` and `heartbeat()` both reject a
  reassigned-away worker, so its late report is discarded.

The coordinator itself is a **single process with no failover** — acceptable for
local dev. Production HA would need leader election (etcd-style), out of scope.

## Running it

```powershell
docker compose --profile distributed up -d --scale dworker=3
```

This starts `kgre-coordinator` (:50051) and 3 `dworker` containers on the shared
network. They use the in-container hostnames (`coordinator`, `neo4j`, `postgres`,
`redis`) from the Compose `environment:` blocks.

> The scheduler is not auto-wired into the standalone `server.py` `serve()` in
> the current code — `coordinator_test.py` drives the registry/scheduler
> directly. Treat the distributed pool as an **experimental, profile-gated**
> layer; the RQ worker is the supported default path.

## Failure test

```powershell
# start a large ingestion, then:
docker kill kgre-worker-1
```

Expected: coordinator logs the worker reaped after ~30s; another worker picks up
the unfinished batch; Neo4j node counts before vs. after reassignment are
**equal** (no double-writes). The `reassignments` / `dead_workers` counters in
`registry.snapshot()` reflect the event.

See [`scripts/coordinator_test.py`](../scripts/coordinator_test.py) for an
in-process version of this test.

Continue to [Sharded knowledge graph](10-sharding.md).
