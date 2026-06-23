# 15 — Operations & troubleshooting

A runbook for the local deployment. For cloud, there is none yet (Phase 7 is
unbuilt by design).

## Daily operation

| Action | How |
|--------|-----|
| Start everything | `.\dev.ps1` |
| Stop everything | `.\dev.ps1 -Stop` (stops the 3 dev processes **and** Docker infra) |
| Fast restart | `.\dev.ps1 -SkipDeps` |
| Check stack health | `curl http://localhost:8000/health/ready` (all three stores `ok`) |
| Check worker/queue | `curl http://localhost:8000/api/system/queue` |
| Inspect the graph | Neo4j Browser at http://localhost:7474 |
| Metrics | `curl http://localhost:8000/metrics` |

The three dev processes each run in their own terminal window
(`kgre-backend`, `kgre-worker`, `kgre-frontend`) — check those windows for logs.

## The stuck-source story

This is the single most important operational concept. A source's status is the
contract with the UI, and the system goes to great lengths to keep it honest.

**The invariant:** a source is only `running` while a worker is actively
processing it. A `success` source must have actually written searchable data.

**How it can break:** the RQ worker process dies (kill, restart, crash, or the
event-loop-disposal bug) mid-source. The source is left stranded at `running`
forever, or — worse — a bug marks it `success` with nothing ingested, so it
shows green but every question returns "no information".

**The defenses, in layers:**

1. **No silent black holes (ingestion job).** A fetch yielding 0 documents, or a
   source whose every document failed, is set to `error` with a descriptive
   `last_error` — never green. ([`jobs.py`](../backend/ingestion/jobs.py))
2. **Terminal-state guarantee.** Everything after the fetch runs inside a
   `try/except` that forces the source to `error` on any raise (stale-loop
   `RuntimeError`, Redis flush failure, cache-invalidation error). The source
   always lands in a terminal state.
3. **Startup recovery.** On boot, [`main.py`](../backend/main.py) resets any
   source still `running` to `error` ("Ingestion worker stopped before this
   source finished. Retry to re-ingest.") — its owning worker is provably gone.
4. **Per-request stuck sweeps.** `GET …/sources` (first-time ingests) and `POST
   …/cleanup` (re-ingests) reset sources stuck `running` past **15 minutes**,
   without needing a backend restart.
5. **Event-loop disposal.** The root cause of one whole class of stranding is
   prevented outright — every job disposes all global async pools in a `finally`
   (see below).

If a source is stuck: click **Re-ingest** in the UI, or `POST
…/sources/{id}/reingest`, or restart the backend (startup recovery handles it),
or `POST …/cleanup`.

## The event-loop-disposal failure

**Symptom:** ingestion works for the first source after a worker start, then the
next source crashes with `RuntimeError: Event loop is closed` — *or* the crash
surfaces only at the Redis flush (because Postgres `pool_pre_ping` transparently
recovers), leaving the source at `running`.

**Cause:** the RQ `SimpleWorker` runs each job via a fresh `asyncio.run()` (new
event loop), but the global async pools (SQLAlchemy, Neo4j, redis.asyncio, shard
router) bind to the loop that created them.

**Fix (already in place):** [`_run_and_cleanup`](../backend/ingestion/jobs.py)
disposes **all** global async pools in a `finally` after every job. Don't remove
this. Regression repro: `python scripts/repro_event_loop_disposal.py --no-fix`
(fails) vs without the flag (passes). This is recorded in project memory as a
permanent invariant.

## Common problems

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Queries return 503 "daily free-tier quota used up" | Gemini RPD quota exhausted | Wait for reset, or set a different `LLM_MODEL`. Run `scripts/test_gemini.py` to confirm. |
| Bursts of 429/503 during ingestion | Gemini RPM limit (extraction fans out windows) | Normal — absorbed by the per-call retry loop; not a real failure. |
| `/health/ready` returns 503 | A store is down | Check `docker compose ps`; the body names the unreachable store. |
| Source stuck at `running` | Worker died mid-source | See [the stuck-source story](#the-stuck-source-story). |
| Source green but answers "no information" | Should not happen now; legacy data | `POST …/cleanup`; re-ingest. |
| `arxiv_feed` source errors with "0 documents" | Bad category/ID, or arxiv blocked the request | Check the `url` field; IDs must exist and be public. |
| Frontend shows connection error | Backend not up / wrong proxy target | Confirm :8000 answers `/health/live`; check `VITE_PROXY_TARGET`. |
| `SSL: CERTIFICATE_VERIFY_FAILED` on fetch | Stale Windows CA store | Already mitigated — fetchers verify against certifi's bundle. Update `certifi`. |
| Worker won't start on Windows | RQ default `Worker` uses `os.fork` | Use `scripts/ingestion_worker.py` (it uses `SimpleWorker`). |
| Document ingested in workspace A, workspace B empty-but-green | Old global-skip bug | Fixed — skip is per-workspace (checks that workspace's Chroma). Re-ingest B. |

## Manual graph inspection (Neo4j)

```cypher
// counts by label / relationship type
MATCH (n) RETURN labels(n)[0] AS type, count(*) ORDER BY count(*) DESC;
MATCH ()-[r]->() RETURN type(r) AS rel, count(*) ORDER BY count(*) DESC;

// a workspace's papers
MATCH (p:Paper {workspace_id:'arxiv_seed'}) RETURN p.name, p.arxiv_id LIMIT 25;

// disputed claims
MATCH (a)-[r]->(b) WHERE r.conflict_flag = true
RETURN a.name, type(r), b.name, r.source_document_id;

// what a given source contributed (precise deletion is built on this list)
MATCH (n) WHERE $sid IN n.source_ids RETURN labels(n)[0], n.name LIMIT 50;
```

## Data reset

| Goal | Action |
|------|--------|
| Remove one source's data precisely | `DELETE …/sources/{id}` (detaches its graph/vector contribution, preserving shared nodes other sources assert). |
| Reclaim orphaned data | `POST …/cleanup`. |
| Wipe a workspace | `DELETE …/workspaces/{id}` (cascades sources/jobs/reports in Postgres; run cleanup to reclaim graph/vector). |
| Nuke everything | `docker compose down -v` (deletes the Neo4j/Postgres/Redis volumes) **and** delete `./chroma_data` (ChromaDB persistence is on the host, not in a volume). |

> Note `chroma_data/` lives on the host filesystem (in-process ChromaDB), so a
> `docker compose down -v` does **not** clear vectors — delete the directory
> separately for a true clean slate.

## Backups

There is no automated backup. For a manual snapshot: dump Postgres
(`pg_dump`), copy the Neo4j data volume, and copy `./chroma_data`. Redis holds
only caches/checkpoints and is safe to lose (it regenerates).

## Scaling levers (when single-node isn't enough)

1. Turn on the **distributed worker pool** (Phase 3) to scale ingestion
   throughput and add fault tolerance — [09](09-distributed-workers.md).
2. Turn on **sharding** (Phase 4) only if a single Neo4j becomes a real
   write/durability ceiling — the [benchmark](10-sharding.md#benchmark-results)
   says it's not worth it at hundreds of entities.
3. Raise per-source concurrency (`_CONCURRENCY` in `jobs.py`) or the LLM bulkhead
   size — but ingestion is Gemini-latency-bound, so the real limit is the API
   quota, not the local code.

Continue to [Glossary](16-glossary.md).
