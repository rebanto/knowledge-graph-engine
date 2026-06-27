# 14 — Scripts

Everything in [`scripts/`](../scripts/). All scripts add the repo root to
`sys.path` and `load_dotenv()`, so run them from the project root with the
virtualenv active. Anything that calls Gemini needs `GEMINI_API_KEY`; the
Phase-4 scripts need the three Neo4j shards up.

## Day-to-day

### `seed_arxiv.py`
One-time graph seed — populates Neo4j + ChromaDB **directly, without the RQ
worker**, and marks the `arxiv_seed` source `success` in Postgres.

```powershell
python scripts/seed_arxiv.py --max 500 --days 90
```

Rate-limits itself to ~1 LLM call / 7s for the free Gemini tier and stops
cleanly on `DailyQuotaExhausted` (resume next day). The fastest way to a
populated graph. See [Getting started → Option A](03-getting-started.md#option-a--seed-from-the-command-line-fastest-first-graph).

### `ask.py`
Run one question against the pipeline from the CLI (workspace `arxiv_seed`):

```powershell
python scripts/ask.py "How is attention related to transformers?"
```

Exercises the full read path (route → retrieve → synthesize) and prints the
answer.

### `ingestion_worker.py`
The **RQ worker entry point** — not a test. Launched by `dev.ps1`. Runs an RQ
`SimpleWorker` (in-process, no `os.fork`, required on Windows) draining the
`ingestion` and `ingestion_bulk` queues. Run it in its own terminal alongside
the API:

```powershell
python scripts/ingestion_worker.py
```

### `detect_conflicts.py`
Retroactive bulk conflict scan over an existing workspace (flags disputed
`SUPPORTS`/`CONTRADICTS` edges and creates `CONFLICTS_WITH`). Useful after
ingesting data under sharding (where inline detection is skipped) or to backfill.

```powershell
python scripts/detect_conflicts.py --workspace arxiv_seed
```

### `test_gemini.py`
Connectivity/quota diagnostic — tries several Gemini models and reports success
or the exact quota/limit error. Run this first when LLM calls fail.

## Verification / test harnesses

These are standalone assertions against **real services**, not a pytest suite.

| Script | Phase | What it proves |
|--------|-------|----------------|
| [`e2e_source_test.py`](../scripts/e2e_source_test.py) | 1–2 | Full source lifecycle for every source type (web/arxiv/rss/pdf) through the **real** `run_ingestion_job` (fetch → process → Neo4j+Chroma → terminal status), then add→query→delete→re-add. Running the job repeatedly in one process is itself the proof of the **event-loop-disposal** fix. |
| [`repro_event_loop_disposal.py`](../scripts/repro_event_loop_disposal.py) | — | Isolated repro of the "Event loop is closed" regression. `--no-fix` skips teardown and **fails**; default uses the fix and **passes**. Needs Redis. |
| [`coordinator_test.py`](../scripts/coordinator_test.py) | 3 | The distributed-worker **failure test**, in-process over real gRPC (no Docker): a worker "crashes" mid-batch, the reaper requeues its docs, a live worker finishes them; asserts nothing lost, a reassignment recorded, the bad worker reaped. |
| [`shard_router_test.py`](../scripts/shard_router_test.py) | 4 | Consistent hashing distributes evenly; a node lands on exactly its hash shard; a cross-shard edge stores a stub target; scatter-gather finds the shared neighbour of two cross-shard entities. Needs shards on 7687/7688/7689. |
| [`sharded_ingest_test.py`](../scripts/sharded_ingest_test.py) | 4 | The **real** ingestion pipeline with `USE_SHARDING=true` writes documents across all 3 shards while ChromaDB and source status behave as in single-node. Needs shards + `GEMINI_API_KEY`. |
| [`benchmark_sharding.py`](../scripts/benchmark_sharding.py) | 4 | Single-node vs 2-shard vs 3-shard latency (single-entity p50/p99, cross-shard relationship p50/p99) over the same live instances. Writes to an isolated benchmark workspace and cleans up. Produces the table in [Sharding](10-sharding.md#benchmark-results). |
| [`benchmark_quality.py`](../scripts/benchmark_quality.py) | eval | Answer-quality benchmark over the golden set: routing accuracy + confusion matrix, retrieval hit-rate, **faithfulness / unsupported-claim rate** (LLM judge), and entity-resolution P/R/F1. Needs the full stack + a seeded workspace; `--no-faithfulness` skips the judge. See [Evaluation](18-evaluation.md). |
| [`benchmark_multihop.py`](../scripts/benchmark_multihop.py) | eval | Runs multi-hop relationship questions down graph-only and vector-only paths (via the `force_route` hook) and prints both answers side by side — the proof that graph traversal does what vector search structurally can't. |

```powershell
# Phase 4 examples
python scripts/shard_router_test.py
python scripts/sharded_ingest_test.py
python scripts/benchmark_sharding.py --entities 300 --queries 200

# Quality / evaluation
python scripts/benchmark_quality.py --workspace arxiv_seed
python scripts/benchmark_multihop.py --workspace arxiv_seed
```

## Note on testing approach

There are two complementary layers:

1. A **`pytest` suite** in [`tests/`](../tests) for pure logic that runs without
   services — chunking, routing/fallback control flow, the Cypher self-correction
   loop, the cross-encoder reranker ordering, three-band entity resolution, the
   graph algorithms (PageRank/communities), and the evaluation metrics. A few
   tests opportunistically hit live Neo4j/Postgres and auto-skip when unavailable.
   Run with `pytest`.
2. These **executable, real-service scripts**, which verify the trickier
   end-to-end invariants (event-loop disposal, worker reassignment, shard
   routing) and produce the benchmark numbers. When changing the ingestion or
   distributed layers, run the relevant harness as your regression check.

Continue to [Operations & troubleshooting](15-operations.md).
