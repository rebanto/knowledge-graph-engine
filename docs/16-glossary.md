# 16 — Glossary

Terms as they're used in this codebase and these docs.

| Term | Meaning |
|------|---------|
| **Workspace** | A research project scoped to a domain. The tenancy boundary for everything: graph nodes, vector collections, sources, reports all carry `workspace_id`. Default seeded workspace is `arxiv_seed`. |
| **Source** | An ingestion input attached to a workspace: an ArXiv feed/ID/query, an RSS feed, a web URL, or an uploaded PDF. Has a status lifecycle (`pending → running → success` \| `error`). |
| **Document** | One item fetched from a source (a paper, an article, a page, a PDF). Produces one `Paper` node + chunks + extracted entities/edges. |
| **Ingestion job** | A Postgres row tracking one document's processing within a source run. |
| **Report** | A saved, versioned answer to a question, with the full retrieval payload in `sources_used` so it re-renders identically. |
| **Entity** | A graph node: `Person`, `Organization`, `Paper`, `Concept`, `Event`, or `Topic`. Domain-agnostic. |
| **Concept** | The workhorse entity type — any technical substance (algorithm, method, architecture, dataset, benchmark, metric, theorem). Extracted aggressively because shared concepts connect documents. |
| **Edge / relationship** | A typed, directed connection between two entities (`AUTHORED`, `MENTIONS`, `CITED`, `SUPPORTS`, …), carrying confidence, source attribution, and conflict flags. |
| **Entity resolution** | Merging duplicate entities that refer to the same real-world thing under slightly different names, via embedding cosine similarity ≥ 0.85 per type. Prevents duplicate nodes. |
| **Entity extraction** | The LLM step that turns document text into `{entities, relationships}` JSON. Windowed over the whole document. |
| **Router** | The Gemini classifier that labels a question `graph`, `vector`, or `hybrid`. |
| **Graph retrieval** | Answering via Cypher over Neo4j — for relationship questions. |
| **Vector retrieval** | Answering via nearest-chunk search over ChromaDB — for knowledge/content questions. |
| **Hybrid** | Running both retrievers in parallel and merging — for questions needing relationships *and* content. The router's default when unsure. |
| **Synthesizer** | The Gemini step that turns retrieved data into a markdown answer + key entities + insight cards, grounded strictly in the retrieved data. |
| **Insight card** | A typed structured element in an answer: `stat_grid`, `bar_chart`, `flow_path`, `comparison_table`, `timeline`. |
| **Idempotency** | The property that re-processing a document produces no duplicates or corruption. Enforced by Neo4j `MERGE`, ChromaDB `upsert` with deterministic IDs, and conditional Postgres updates. |
| **Source attribution** | The `source_ids` list on every node/edge recording which Postgres sources asserted it — the basis for precise source deletion. |
| **Checkpoint** | The last-processed document URL for a source, stored in Redis, enabling crash-resume mid-source. |
| **Conflict / `CONFLICTS_WITH`** | Auto-created when two different sources make opposing `SUPPORTS`/`CONTRADICTS` claims about the same entity pair. Both claim edges get `conflict_flag=true`. |
| **DLQ** | Dead-letter queue (`ingestion_dlq`) — documents that exhausted retries, kept for manual inspection/replay. |
| **RQ / SimpleWorker** | Redis Queue. The default ingestion worker uses RQ's `SimpleWorker` (in-process, no `os.fork`) because Windows lacks `fork`. Runs one `asyncio.run()` per job. |
| **Event-loop disposal** | The mandatory teardown of all global async DB pools after each worker job, because each job runs in a fresh event loop. Omitting it crashes the next job with "Event loop is closed". |
| **Bulkhead** | A dedicated thread pool isolating slow synchronous I/O (Gemini SDK, ChromaDB) so it can't starve other pools. |
| **Circuit breaker** | A `pybreaker` guard per external dependency that opens after repeated failures to stop cascading. Note the Gemini call is checked-but-not-routed-through the breaker (see [Resilience](12-resilience-observability.md)). |
| **Coordinator** | Phase 3: the single gRPC process that hands document batches to workers and reaps dead ones. |
| **Worker (distributed)** | Phase 3: a gRPC client that registers, requests batches, heartbeats, and processes documents via the same `process_document` pipeline. |
| **Heartbeat / reaper** | Phase 3: workers send liveness pings; the reaper declares silent workers dead and requeues their batches. |
| **Batch** | Phase 3: a unit of documents assigned to one worker. |
| **Shard** | Phase 4: one of N Neo4j instances. An entity's shard is `sha256(name.lower()) % NUM_SHARDS`. |
| **Shard router** | Phase 4: the layer presenting N shards as one logical graph, with the same write surface as the single-node driver. |
| **Scatter-gather** | Phase 4: querying multiple shards in parallel and merging — used for cross-shard relationship queries (intersecting neighbour sets). |
| **Stub node** | Phase 4: a lightweight (`is_stub=true`, name+type only) stand-in for a cross-shard edge's target, so the relationship is traversable on the source shard. |
| **Seed** | Populating the graph from ArXiv via `scripts/seed_arxiv.py`, bypassing the worker. |

---

## Cross-reference: where each concept is implemented

| Concept | Primary file(s) |
|---------|-----------------|
| Query orchestration | [`core/qa_pipeline.py`](../backend/core/qa_pipeline.py) |
| Routing | [`core/router.py`](../backend/core/router.py) |
| Graph retrieval / Cypher safety | [`core/graph_retriever.py`](../backend/core/graph_retriever.py) |
| Vector retrieval | [`core/vector_retriever.py`](../backend/core/vector_retriever.py) |
| Synthesis | [`core/synthesizer.py`](../backend/core/synthesizer.py) |
| LLM client (Gemini) | [`core/llm_client.py`](../backend/core/llm_client.py) |
| Ingestion orchestration / DLQ / loop disposal | [`ingestion/jobs.py`](../backend/ingestion/jobs.py) |
| Per-document pipeline | [`ingestion/worker.py`](../backend/ingestion/worker.py) |
| Extraction / resolution / conflicts | [`ingestion/entity_extractor.py`](../backend/ingestion/entity_extractor.py), [`entity_resolver.py`](../backend/ingestion/entity_resolver.py), [`conflict_detector.py`](../backend/ingestion/conflict_detector.py) |
| Single-node graph writes | [`db/neo4j.py`](../backend/db/neo4j.py) |
| Sharding | [`db/shard_router.py`](../backend/db/shard_router.py) |
| Caching / checkpoints / resolver registry | [`db/redis.py`](../backend/db/redis.py) |
| Vector store | [`db/chroma.py`](../backend/db/chroma.py) |
| Distributed pool | [`coordinator/`](../backend/coordinator/), [`proto/coordinator.proto`](../proto/coordinator.proto) |
| Resilience / observability | [`core/resilience.py`](../backend/core/resilience.py), [`core/observability.py`](../backend/core/observability.py) |
| API | [`api/routes/`](../backend/api/routes/) |
| Frontend | [`frontend/src/`](../frontend/src/) |

Back to the [documentation index](README.md).
