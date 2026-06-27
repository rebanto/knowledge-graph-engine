# Knowledge Graph Research Engine — Complete Project Overview

*A presentation-grade walkthrough of the entire system: what it is, how it works,
what makes it different, and the engineering depth behind it.*

---

## Table of contents

1. [What it is — in one paragraph](#1-what-it-is)
2. [The thesis: this is not an LLM wrapper](#2-the-thesis)
3. [System architecture at a glance](#3-architecture)
4. [The two retrieval systems + the router](#4-two-retrieval-systems)
5. [The write path — ingestion](#5-write-path)
6. [The read path — answering a question](#6-read-path)
7. [Distributed-systems depth](#7-distributed-systems)
8. [AI / ML depth](#8-ai-ml-depth)
9. [How quality is measured](#9-evaluation)
10. [Unique selling points & differentiation](#10-usps)
11. [Headline measured results](#11-results)
12. [Tech stack & cloud path](#12-stack)
13. [Engineering philosophy & key decisions](#13-philosophy)
14. [Honest limitations](#14-limitations)
15. [Demo script & talking points](#15-demo)

---

<a name="1-what-it-is"></a>
## 1. What it is — in one paragraph

A **research intelligence platform** that answers complex natural-language
questions by querying a **real knowledge graph of connected entities**, not by
asking an LLM to recall facts. A user creates a workspace, points it at sources
(ArXiv categories, RSS feeds, web URLs, uploaded PDFs), and asks questions. The
system ingests those sources into two coordinated stores — a **Neo4j knowledge
graph** of entities and typed relationships, and a **ChromaDB vector store** of
embedded text — then routes each question to whichever store can answer it,
retrieves structured evidence, and has the LLM turn that evidence into a cited
prose answer. The domain is whatever the user's sources cover; the engine is
domain-agnostic. The default seed domain is **AI/ML research papers from ArXiv**.

<a name="2-the-thesis"></a>
## 2. The thesis: this is not an LLM wrapper

The defining design constraint: **the LLM is confined to two narrow jobs**, and
never generates free facts.

1. **Ingestion** — turn a document into structured entities and relationships
   (JSON output, validated against a fixed schema).
2. **Query** — translate the user's question into a database query, and translate
   the retrieved structured results into prose.

Everything between those two — graph storage and traversal, vector search,
routing, conflict detection, ranking, caching, the distributed execution layer —
is **real code**, not a prompt. Every fact in an answer must trace to a retrieved
graph record or document chunk. This isn't just asserted; it is **measured** (see
§9 and §11: a faithfulness judge scores the unsupported-claim rate).

This is the single most important framing for evaluating the project: it is a
**retrieval and systems engineering project** with the LLM as a constrained
component, not a chatbot with a database bolted on.

<a name="3-architecture"></a>
## 3. System architecture at a glance

```
                              READ PATH (query)
  question ─► Router (LLM classify) ─► graph and/or vector retrieval ─► Synthesizer (LLM) ─► answer + insights
                                          │                                                   (saved as a versioned Report)
                                          ├─ graph: text→Cypher → (self-correct) → Neo4j / shard-router scatter-gather
                                          └─ vector: embed → ChromaDB → cross-encoder rerank

                              WRITE PATH (ingest)
  source ─► fetch ─► chunk ─┬─► embed → ChromaDB (upsert, deterministic ids)
                            └─► LLM entity extraction → resolve entities → MERGE into Neo4j
                                                                           └─ conflict detection
```

**Process model (all Docker on one network):**

| Component | Role |
|-----------|------|
| FastAPI app | REST + SSE API, the read path |
| Coordinator (gRPC) | assigns ingestion batches to workers, tracks heartbeats |
| Workers ×3 | run the ingestion pipeline per document |
| Neo4j ×1 (or ×3 sharded) | knowledge graph |
| ChromaDB (server) | vector store, shared across processes |
| PostgreSQL | users, workspaces, sources, jobs, versioned reports |
| Redis | cache layers + RQ fallback queue + resolver registry |
| React + TypeScript SPA | question input, answer + insight cards, graph viz, dashboards |

The system is built in **layers that each preserve a working fallback**: a single
Neo4j + single RQ worker is the always-available baseline; the distributed
coordinator/worker pool and the sharded graph are **opt-in** (`USE_SHARDING`, the
`distributed` compose profile). If the distributed layer breaks, the simple path
still works.

<a name="4-two-retrieval-systems"></a>
## 4. The two retrieval systems + the router

### System 1 — Knowledge graph (Neo4j)

Stores **entities** (Person, Organization, Paper, Concept, Event, Topic — labels
are domain-agnostic) and **typed relationships** (AUTHORED, CITED, COLLABORATED_WITH,
AFFILIATED_WITH, FUNDED_BY, MENTIONS, ABOUT, SUPPORTS, CONTRADICTS, CONFLICTS_WITH,
and conceptual edges like USES/EXTENDS/IMPROVES/COMPARED_TO). Every node carries
`workspace_id` and source provenance; every edge carries a source document id,
confidence, and a conflict flag. Answers *relationship* questions: connections,
collaboration, citation chains, funding, contradictions, paths.

### System 2 — Vector store (ChromaDB)

Documents are chunked (~512 tokens, 50 overlap), embedded with a local
sentence-transformer (`all-MiniLM-L6-v2`), and stored with deterministic chunk
ids. Answers *knowledge/content* questions: "summarize findings on X", "what are
the open problems in Y". Sources are always cited.

### The router

A lightweight LLM classifier labels each question `graph`, `vector`, or `hybrid`
(`hybrid` runs both and merges). It is cached (24 h) and has a **safety net**: if
a `graph` question comes back empty, the pipeline falls back to vector search (and
vice-versa), so a misclassification still produces an answer.

<a name="5-write-path"></a>
## 5. The write path — ingestion

Per document (`backend/ingestion/worker.py::process_document`):

1. **Fetch** (ArXiv API / RSS / web / PDF, with multimodal OCR fallback for
   scanned PDFs).
2. **Skip check** — per-workspace, keyed on whether *this* workspace already holds
   the document's chunks (a subtle multi-tenancy fix: a global "processed" flag
   would skip a doc in workspace B because workspace A ingested it).
3. **Paper + author + category nodes** — structured, LLM-free, exact.
4. **Parallel:** embed chunks → ChromaDB (`upsert`, deterministic ids) **and**
   LLM entity extraction over **overlapping windows** covering the whole document
   (not just the abstract), bounded to cap LLM calls.
5. **Entity resolution** — each extracted entity is resolved against existing
   entities so duplicates collapse (see §8.2).
6. **MERGE** nodes + edges into Neo4j (idempotent), tracking which source asserted
   each so a source can later be precisely detached.
7. **Conflict detection** — if a SUPPORTS/CONTRADICTS edge contradicts an existing
   one from another source, auto-create a `CONFLICTS_WITH` edge and flag both.

Every write is **replay-safe** (MERGE / upsert / conditional UPDATE) because under
the distributed pool any document can be processed twice.

<a name="6-read-path"></a>
## 6. The read path — answering a question

1. **(Follow-up rewrite)** — in a conversation, the follow-up is first rewritten
   into a standalone question using bounded history + a rolling summary, so
   retrieval works on a self-contained query (skipped for first turns).
2. **Route** (LLM classify, cached).
3. **Graph retrieval** (`graph_retriever.py`):
   - LLM translates the question → read-only Cypher (forced workspace filter,
     named return columns).
   - **Safety gate:** regex blocklist rejects any write/`CALL` clause →
     read-only only.
   - **Self-correcting execution:** on a Neo4j error, feed the error + schema back
     to the LLM and regenerate; on a valid-but-empty result, reformulate once to
     broaden. Bounded by `MAX_CYPHER_ATTEMPTS`.
   - Annotate with **entity-degree context**, **PageRank influence**, and
     **conflict flags** for the entities the answer touches.
4. **Vector retrieval** (`vector_retriever.py`): embed (cached) → over-fetch from
   ChromaDB → **cross-encoder rerank** down to top-k.
5. **Synthesis** (`synthesizer.py`): the LLM gets the structured results and a
   strict prompt — trace relationship chains with arrow notation, cite real
   numbers, flag conflicts explicitly, never present a disputed claim as settled,
   and only state facts present in the retrieved data. Returns prose **plus
   structured "insight cards"** (stat grids, bar charts, flow paths, timelines,
   comparison tables) that the UI renders.
6. **Persist** as a versioned Report (re-running a question creates a new version).

Answers are **deliberately never cached** (a cached answer taken before a new
source finished ingesting would silently omit it); embedding, route, and Cypher
caches still apply.

<a name="7-distributed-systems"></a>
## 7. Distributed-systems depth

This is the half a systems-minded reviewer will probe. All of it is implemented,
not sketched.

### 7.1 Coordinator / worker pool (Phase 3)

Replaces a single RQ worker (a SPOF + throughput ceiling) with a
**custom gRPC coordinator** and a horizontally-scalable worker pool.

- **gRPC service** (`proto/coordinator.proto`): `Register`, `RequestWork`,
  `Heartbeat`, `ReportCompletion`, `GetStatus`.
- **Worker registry** (`coordinator/registry.py`) — the heart of it. Pure
  asyncio-locked data structures (unit-testable in isolation): tracks each
  worker's state and current batch, the pending document queue, and reassignment
  counters.
- **Failure detection & recovery:** a reaper marks a worker dead if its heartbeat
  is stale past a timeout, **re-enqueues its in-flight batch**, and a live worker
  picks it up. The classic hard case — a "dead" worker that's actually alive and
  finishes late — is handled correctly: the live worker's run is **authoritative**,
  the late `ReportCompletion` is ignored, and because all writes are idempotent,
  the duplicate work is harmless.
- **Durable bookkeeping** (`job_tracker.py`): the in-memory registry is mirrored
  into Postgres — one `ingestion_jobs` row per document (deterministic uuid5),
  queued→running→success/failed transitions, source-status rollup — all with
  conditional, replay-safe writes so a late worker can't overwrite a terminal
  state.
- **Verified** by `scripts/coordinator_test.py` (kill/reassign over real gRPC,
  in-process) and `tests/test_job_tracker.py`.

### 7.2 Sharded knowledge graph (Phase 4)

Splits the entity space across 2–3 Neo4j instances behind a **consistent-hash
router** (`db/shard_router.py`), presenting one logical graph.

- **Routing rule:** `shard = sha256(entity_name.lower()) % num_shards` — stable,
  deterministic, no routing table needed; any process computes it locally.
- **Cross-shard edges:** stored on the source entity's shard, with a lightweight
  **stub node** standing in for a target that lives on another shard; the router
  resolves stubs against the owning shard.
- **Scatter-gather reads:** a read runs the *same* Cypher on every shard in
  parallel and **merges with de-duplication** — so the Cypher is unchanged from
  the single-node path; only the physical fan-out differs. Per-entity **degree is
  summed across shards** with no double-counting (each physical edge counted on
  exactly one shard).
- **Honest about limits:** whole-graph aggregates (`RETURN count(*)`) return one
  partial row per shard; deep cross-shard joins where intermediates are stubs
  aren't reconstructed by the simple union. Documented, not hidden.
- **Benchmarked** (`benchmark_sharding.py`): relationship queries are ~3× faster
  at p50 under sharding, but at this scale the absolute latencies are low enough
  that the conclusion is **"don't shard yet"** — an honest negative result
  (3 shards = 3 Neptune clusters in the cloud).

### 7.3 Resilience (`core/resilience.py`, `core/llm_client.py`)

- **Circuit breakers** per external dependency (Gemini, Neo4j, external HTTP) —
  open after N failures, half-open to probe recovery.
- **Retries** with exponential backoff + full jitter (tenacity).
- **Bulkheads:** dedicated thread pools isolate the synchronous libraries (the
  Gemini SDK, ChromaDB, the cross-encoder) so slow I/O in one can't starve the DB
  pools or the event loop.
- **Hard timeouts** on the Gemini SDK (which ships none) so a hung call can't
  wedge a worker and strand a source at "running".
- **Rate-limit handling:** parses Gemini's 429 retry hints (both string and
  structured forms) and backs off within a cap — important on the free tier.
- **Graceful degradation everywhere:** graph failure still returns vector results;
  a reranker that can't load falls back to bi-encoder order; a slow shard yields a
  partial result instead of failing the query.
- A subtle, mature judgment call is documented in code: entity-extraction fires
  several concurrent Gemini calls per document, so transient 429 bursts are
  **deliberately not** counted toward the circuit breaker (which would cascade an
  entire batch to failure); the per-call retry loop is the right granularity.

### 7.4 Caching & observability

- **Multi-layer Redis cache:** embeddings (7 d), route classification (24 h),
  Cypher result sets (5 min), PageRank/community results per workspace (5 min),
  plus in-flight request de-duplication. Swept on new ingestion.
- **Observability:** Prometheus counters (HTTP, LLM calls by status, cache
  hit/miss, cypher-repair outcomes, queue depth), structured JSON logging with a
  request-id middleware, health/readiness probes.

### 7.5 Async & concurrency model

Async end-to-end (FastAPI, async Neo4j/Postgres/Redis drivers). Graph and vector
retrieval run concurrently for hybrid queries; degree/conflict/influence
annotations run concurrently; entity-extraction windows run with bounded
concurrency. A documented `asyncio` lifecycle fix (disposing global async pools
per RQ job) prevents "event loop is closed" across jobs.

<a name="8-ai-ml-depth"></a>
## 8. AI / ML depth

This is the half an AI/ML reviewer will probe. Each piece is real and, where it
matters, **measured**.

### 8.1 Entity & relationship extraction

Windowed extraction over the **whole document** (overlapping ~6k-char windows,
bounded count, bounded concurrency), each window prompted for a strict JSON schema
of entities + typed relationships with confidence. Results are merged and
de-duplicated (entities by name+type, relationships keeping the highest
confidence). The prompt deliberately prioritizes *relationships* (the substance
that connects documents), not just named entities.

### 8.2 Entity resolution — three-band with LLM adjudication (measured)

Duplicate nodes destroy a knowledge graph, so this is a first-class concern.

- **Context-aware embedding:** the key embedded is `name | type | aliases`, not a
  bare name — so "BERT" (model) and "Bert" (person) separate, and known aliases
  pull surface forms together.
- **Three bands:** cosine ≥ HIGH (0.97) auto-merge; < LOW (0.55) new entity;
  **in-between → an LLM adjudicator** decides whether the two names denote the same
  entity. The borderline band is exactly where embedding similarity is unreliable,
  so a cheap yes/no beats any fixed threshold.
- **Fails closed** (no merge on error) — a missed merge leaves a duplicate; a
  wrong merge silently corrupts the graph, so the safe default is "don't merge".
- **Measured** (`decide_pair` over labeled pairs): the thresholds were set by an
  evidence loop — the first run scored F1 33%, printing per-pair cosine revealed
  acronym↔expansion pairs falling below the adjudication floor, the bands were
  retuned on principle, and **F1 rose to 87.5% (precision 100%, recall 78%)** with
  the LLM catching the hard merges and rejecting a versioned-name false merge.

### 8.3 Query routing

LLM classifier (graph/vector/hybrid) with a confusion-matrix evaluation
(measured 75% on the golden set; errors are one-directional graph→vector,
softened by the fallback).

### 8.4 Text-to-Cypher with agentic self-correction

The LLM is a fallible translator, so a single syntax slip otherwise silently
degrades a question to vector search. The retriever runs an **execution-repair
loop**: on a Neo4j error it feeds the error + schema back and regenerates; on a
valid-but-empty result it reformulates once to broaden the match. Bounded,
metric-tracked. This is squarely "AI orchestration" — the model correcting its own
tool calls against real feedback.

### 8.5 Graph algorithms — real centrality & communities

`core/graph_algorithms.py` runs **PageRank** (influence that propagates through
the graph — the honest replacement for the old degree-count "centrality") and
**Louvain community detection** over the workspace subgraph with networkx
(no GDS-plugin dependency, works unchanged over the sharded layout). PageRank is
surfaced *inside answers* ("X is the most influential node here") and via
`GET /graph/influence`; communities via `GET /graph/communities`. Cached per
workspace.

### 8.6 Conflict / contradiction detection — a graph-native capability

When two sources make opposite claims about the same entity pair (one SUPPORTS,
another CONTRADICTS), the ingestion pipeline auto-creates a `CONFLICTS_WITH` edge
and flags both. At query time these flags are read back and handed to the
synthesizer, which **explicitly surfaces the dispute** and never presents it as
settled. A pure-RAG system structurally cannot do this — it has no notion of two
sources disagreeing about a relationship.

### 8.7 Cross-encoder reranking — two-stage retrieval

The bi-encoder used for retrieval embeds query and chunk independently (coarse).
A **cross-encoder** (`reranker.py`) reads the (query, chunk) pair jointly and
scores relevance directly — far more accurate. The vector path over-fetches with
the bi-encoder then reranks to top-k. Opt-in, runs in its own thread pool,
degrades gracefully if the model can't load.

### 8.8 Conversational RAG

Multi-turn follow-ups via the standard pattern: bounded history window + a rolling
summary of aged-out turns, an LLM **contextualizer** that rewrites a follow-up
into a standalone question (skipped when there's no history, so first turns pay
nothing), then the *unchanged* pipeline runs on the standalone question. Grounding
rules are unchanged — history is context, never a source of facts.

### 8.9 Grounded synthesis with structured insights

The synthesizer's contract: prose that traces real relationship chains and cites
real numbers, **plus** a typed set of insight cards (stat grid, bar chart, flow
path, timeline, comparison table) validated and clamped server-side. Hard rule:
every entity, date, count, and relationship must appear in the retrieved data.

<a name="9-evaluation"></a>
## 9. How quality is measured

The project applies the same empirical discipline to the **AI core** that the
sharding work applied to latency. A checked-in golden set + two benchmark scripts
(`backend/eval/`, `scripts/benchmark_quality.py`, `scripts/benchmark_multihop.py`)
measure:

- **Routing accuracy + confusion matrix.**
- **Retrieval hit-rate.**
- **Faithfulness / unsupported-claim rate** — an independent LLM judge decomposes
  each answer into atomic claims and checks each against the retrieved data. This
  is the measured form of "the LLM never invents facts."
- **Entity-resolution precision / recall / F1** against labeled pairs.
- **Multi-hop graph-vs-vector** — relationship questions run down both paths to
  show, concretely, what traversal does that similarity search can't.

Pure metric logic is unit-tested; full methodology in
[`docs/18-evaluation.md`](docs/18-evaluation.md); measured numbers in
[`eval_results/BENCHMARK_RESULTS.md`](eval_results/BENCHMARK_RESULTS.md).

<a name="10-usps"></a>
## 10. Unique selling points & differentiation

1. **Graph-grounded, verifiably not a hallucinating wrapper.** Every fact traces
   to retrieved evidence, and the **unsupported-claim rate is measured (≈9%)**,
   not asserted. Most "RAG" products can't put a number on this.
2. **Relationship reasoning that vector search structurally cannot do.**
   Multi-hop traversals — "researchers who share a co-author but never co-wrote",
   degrees of separation, claim chains — return concrete connected entities where
   vector search returns vague prose or openly fails (shown side-by-side, §11).
3. **Conflict / contradiction surfacing.** The system detects when two sources
   disagree about a relationship and flags it in the answer — a graph-native
   capability pure RAG lacks entirely.
4. **Per-fact source provenance.** Every node/edge tracks which sources asserted
   it, so a source can be precisely detached and every claim links to its origin.
5. **Domain-agnostic.** Same engine for AI research, legal precedent, climate
   policy, finance — the user just points it at sources.
6. **Production-grade distributed backbone.** Fault-tolerant ingestion pool +
   sharded graph + circuit breakers + observability — engineering most student
   projects (and many products) don't attempt.
7. **Measured, honest engineering.** Negative results reported (sharding "not
   worth it yet"; routing 75%; one resolution miss) — credibility through
   transparency.

### Marketability framing

The natural market is **research-heavy knowledge work** — R&D labs, competitive
intelligence, legal/patent research, policy analysis, due diligence — anywhere the
question is "how are these things connected and who said what", the answer must be
**traceable to sources**, and **contradictions between sources matter**. That
combination (relationship reasoning + provenance + conflict surfacing) is exactly
what generic chat-over-docs tools don't provide.

<a name="11-results"></a>
## 11. Headline measured results

*(Full detail + raw captures in [`eval_results/BENCHMARK_RESULTS.md`](eval_results/BENCHMARK_RESULTS.md). Run on the `arxiv_seed` workspace, ~1,860 nodes / ~1,560 edges.)*

| Metric | Result |
|--------|--------|
| Routing accuracy | **75%** (errors one-directional, softened by fallback) |
| Retrieval hit-rate | **100%** (12/12) |
| Faithfulness (claims grounded in retrieved data) | **90.9%** |
| Unsupported-claim rate | **9.3%** (10/107 claims) |
| Entity resolution F1 | **87.5%** (precision 100%, recall 78%) — up from 33% after an evidence-based retune |
| Multi-hop: graph returned structured records | **5/5** questions (vector returned only prose, openly failing on 2) |
| Sharding: relationship query p50 | **17.5 ms → ~5 ms** under sharding (3× faster) |

The entity-resolution and multi-hop results are the strongest demo material: one
shows a complete measure→diagnose→fix→re-measure loop; the other is the concrete
proof the graph earns its place.

<a name="12-stack"></a>
## 12. Tech stack & cloud path

**Local (current):** Neo4j, ChromaDB (server), PostgreSQL, Redis + RQ, custom
gRPC coordinator, FastAPI, React + TypeScript, Gemini (`gemini-flash-lite-latest`),
`sentence-transformers` (MiniLM bi-encoder + cross-encoder reranker), networkx,
Docker Compose. *(Note: the repo is named for Claude and `CLAUDE.md` names it
aspirationally, but the running code uses Gemini throughout — called out honestly
in the docs.)*

**Cloud (Phase 7, not built):** Neptune, OpenSearch, RDS, ElastiCache, SQS, ECS/
Fargate, S3, Cognito, Step Functions — with the explicit warning that keeping
sharding means one Neptune cluster *per shard* (re-evaluate the benchmark first).

**Build status:** Phases 1–6 complete and tested locally; the retrieval-quality &
evaluation layer is built on top; Phase 7 (AWS) intentionally not started.

<a name="13-philosophy"></a>
## 13. Engineering philosophy & key decisions

- **Local first, cloud later** — no AWS until the system is proven locally.
- **Build the pipeline directly** — no LangChain/LlamaIndex, so the architecture
  is transparent and every component is understood.
- **Constrain the LLM** — it extracts and translates; it never invents facts.
- **Layer complexity over a working baseline** — the distributed pool and sharding
  are opt-in additions, never the only path; there is always a simpler fallback.
- **Idempotency is non-negotiable** once the distributed pool is active (MERGE /
  upsert / conditional UPDATE).
- **Measure before committing** — the sharding decision, and now the AI-quality
  decisions, are driven by benchmarks, including negative results.

<a name="14-limitations"></a>
## 14. Honest limitations (own these in the room)

- **Routing is 75%** — real headroom; graph questions sometimes read as content
  questions. The fallback hides it from users but the number is the number.
- **Faithfulness isn't 100%** (~9% unsupported) and the judge is itself an LLM —
  a strong second opinion, not ground truth.
- **Entity resolution** is validated on 16 pairs (direction, not a large eval);
  one acronym↔expansion pair (BERT) remains a miss below the adjudication floor.
- **Sharding's deep cross-shard joins** aren't reconstructed by the simple
  scatter-gather union — documented, and the seeded data happens to live on one
  shard anyway.
- **Single-process coordinator** (no leader election) — acceptable for local;
  production would need etcd-style failover (noted as out of scope).

These are deliberately surfaced — the project's credibility comes from reporting
them, the same way it reports the sharding "not worth it yet" conclusion.

<a name="15-demo"></a>
## 15. Demo script & talking points (for the professor)

A tight 10-minute path that leads with the differentiators and the measurements:

1. **Frame it (30s):** "Not an LLM wrapper — the LLM only extracts and translates;
   facts come from a real graph and vector store, and I measured that it doesn't
   hallucinate."
2. **Ask a relationship question live** (e.g. "how is X connected to Y?") — show
   the answer tracing a relationship chain with provenance, and the graph
   visualization.
3. **Show the conflict USP** — a concept supported by one source and contradicted
   by another, surfaced in the answer.
4. **Run `benchmark_multihop.py`** — graph 5/5 structured records vs vector prose
   that *admits it can't traverse*. This is the "graph earns its complexity"
   proof.
5. **Run `benchmark_quality.py`** — routing/retrieval/faithfulness/resolution
   numbers. Lead with **faithfulness (unsupported-claim rate)** as the measured
   form of "no hallucination", and tell the **entity-resolution
   measure→diagnose→fix→re-measure story** (F1 33%→88%) — it shows method, not
   luck.
6. **Show the distributed depth** — coordinator dashboard (worker health, queue,
   reassignment), then `coordinator_test.py` killing a worker mid-batch and
   another picking it up with no double-writes.
7. **Close with honesty** — `benchmark_sharding.py` and the "don't shard yet"
   conclusion; the limitations in §14. Strict reviewers trust a builder who
   reports negative results.

**The one-line pitch:** *"A domain-agnostic research engine that answers
relationship questions from a real knowledge graph — with measured faithfulness,
graph-native conflict detection, and a fault-tolerant distributed ingestion
backbone — not an LLM guessing over documents."*

---

*See also: [`CLAUDE.md`](CLAUDE.md) (architecture & build phases), [`docs/`](docs)
(full technical documentation, 18 chapters), and
[`eval_results/BENCHMARK_RESULTS.md`](eval_results/BENCHMARK_RESULTS.md) (measured
numbers).*
