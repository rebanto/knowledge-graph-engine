# Knowledge Graph Research Engine — Project Context

This file is read automatically by Claude Code at the start of every session.
Do not delete it. Update it as the project evolves.

---

## What This Project Is

A research intelligence platform that answers complex questions by querying a
real knowledge graph of connected entities — not by asking an LLM to guess.

The system is fully domain-agnostic. A user creates a workspace, points it
at sources (RSS feeds, ArXiv categories, uploaded PDFs, web URLs), and asks
questions in natural language. The domain is whatever the user's sources cover
— AI research, climate policy, legal precedent, financial markets, geopolitics,
materials science, or anything else. The engine does not know or care.

The user types a natural language question. A router decides whether to answer
it via graph traversal (relationship questions) or vector search (knowledge
retrieval questions). The LLM only translates questions into queries and
translates results into readable prose. It does not generate facts.

**This is not an LLM wrapper.** The LLM touches two narrow jobs:
1. Extracting entities and relationships from documents during ingestion
2. Translating the user's question into a query, and query results into prose

Everything in between — graph storage, traversal, vector search, routing,
conflict detection, caching — is real code.

---

## The Core Architecture

Query path (unchanged by distributed additions):

```
User question
      |
 Query Router
 (LLM classifies question type)
      |
   ┌──┴────────────────────────┐
   |                           |
Shard Router               Vector Search
(hashes entity names,      (ChromaDB)
 queries 1-3 Neo4j shards) (knowledge Q's)
   |                           |
   └──────────┬────────────────┘
              |
       Result Synthesizer
       (LLM turns structured results into prose)
              |
         Report (saved, versioned, shareable)
```

Ingestion path (Phase 3+ uses the coordinator/worker architecture):

```
Source (RSS / ArXiv API / uploaded PDF)
      |
 Coordinator Process
 (listens for worker connections via gRPC,
  assigns document batches, tracks heartbeats)
      |
   ┌──┴──────────────────────────────┐
   |             |                   |
Worker 1      Worker 2           Worker 3
(Docker        (Docker            (Docker
 container)     container)         container)
   |             |                   |
   └──────────┬──┴───────────────────┘
              |
         Shard Router
         (consistent hash on entity name)
              |
      ┌───────┼───────┐
  Shard 0  Shard 1  Shard 2     ChromaDB
  (Neo4j)  (Neo4j)  (Neo4j)  (vector store)
```

Phases 1-2 use a single Neo4j and a single RQ worker — the simpler diagram
still applies during those phases. The distributed architecture is layered on
top in Phases 3 and 4.

---

## Two Retrieval Systems

### System 1 — Knowledge Graph (Neo4j)

Stores entities and the relationships between them.

- **Nodes:** Person, Organization, Paper, Concept, Event, Topic
  - Node types are domain-agnostic. A "Concept" can be a drug, a legal
    principle, a financial instrument, a programming language — anything.
    The entity extractor infers the appropriate label from context.
- **Edges:** AUTHORED, CITED, FUNDED_BY, CONFLICTS_WITH, COLLABORATED_WITH, PUBLISHED_IN
- **Each edge has:** source document, confidence score, timestamp, conflict flag
- **Queries written in:** Cypher (Neo4j native)
- **Algorithms used:** shortest path, PageRank centrality, community detection,
  contradiction detection (when two sources make conflicting claims about an edge)
- **Sharding (Phase 4+):** 2-3 Neo4j instances behind a shard router. See the
  "Sharded Knowledge Graph" section below for details.

Good for questions like (examples span multiple domains):
- "How is researcher X connected to organization Y?"
- "Which papers that cited Study A later contradicted it?"
- "What institutions are funding research into Topic X?"
- "Who has collaborated with Person X across multiple fields?"
- "What is the chain of influence between Concept A and Concept B?"

### System 2 — Vector Search (ChromaDB locally)

Stores embedded chunks of ingested documents for semantic similarity search.

- Documents are chunked (~512 tokens), embedded via an embedding model, stored
- At query time: user question is embedded, nearest chunks retrieved, LLM
  synthesizes an answer from those chunks with source citations
- Sources are always cited — the LLM never generates unsourced facts

> **ChromaDB runs as a SERVER, not in-process.** The API and the RQ ingestion
> worker are separate OS processes. A per-process `PersistentClient` caches the
> collection/HNSW index in memory and never sees another process's writes — so
> the worker would ingest data the API can never retrieve (source shows green
> "ready", every question answers "no information"). Both processes connect to
> ONE shared Chroma server (`kgre-chroma` container, host port 8001) via
> `chromadb.HttpClient`, configured by `CHROMA_HOST`/`CHROMA_PORT`. The embedded
> `PersistentClient` is used ONLY by single-process code (the seed script and
> unit tests, where `CHROMA_HOST` is unset). Do NOT revert to an in-process
> client for the API/worker — it silently breaks all retrieval.

Good for questions like (examples span multiple domains):
- "What are the latest findings on Topic X?"
- "Summarize the current state of research on Concept Y"
- "What are the open problems in Field Z?"
- "What evidence exists for or against Claim X?"

### The Router

A lightweight LLM classifier that receives the user's question and outputs one
of: `graph`, `vector`, or `hybrid`.

`hybrid` runs both pipelines and merges results — used for questions that ask
about both relationships AND knowledge content.

---

## Distributed Worker Pool (Phase 3)

Replaces the simple single-process RQ worker from Phases 1-2. The pipeline
logic (fetch → chunk → extract → write) does not change; only the execution
layer changes.

### Why

A single RQ worker is a single point of failure and a throughput ceiling. The
coordinator/worker model makes the ingestion layer horizontally scalable and
fault-tolerant: workers can be added, fail, or restart without losing work.

### Architecture

**Coordinator** — a single long-running process (one Docker container) that:
- Listens for incoming worker connections on a gRPC port.
- Maintains a registry of active workers (name, state, current batch).
- Pulls pending ingestion jobs from PostgreSQL and assigns batches to workers
  that have called `RequestWork`.
- Receives heartbeat RPCs from each worker every few seconds containing the
  worker's current status and progress within its batch.
- If a worker's heartbeat is not received within a configurable timeout (default
  30 s), marks it dead in the registry and re-enqueues its unfinished jobs.

**Worker** — one or more Docker containers (target: 3 in local dev), each:
- Connects to the coordinator's gRPC address on startup and calls `Register`.
- Calls `RequestWork` to receive a batch of document URLs to ingest.
- Processes each document through the existing pipeline (fetch → chunk →
  extract → write to Neo4j + ChromaDB).
- Sends a `Heartbeat` RPC every 5 seconds with `{worker_id, status, completed,
  total}`.
- Calls `ReportCompletion` when the batch is done (success or partial failure).

**gRPC service definition** (to be placed in `proto/coordinator.proto`):
```
service Coordinator {
  rpc Register(RegisterRequest)       returns (RegisterResponse);
  rpc RequestWork(WorkRequest)        returns (WorkBatch);
  rpc Heartbeat(HeartbeatRequest)     returns (HeartbeatAck);
  rpc ReportCompletion(BatchResult)   returns (CompletionAck);
}
```

### Failure Recovery and Idempotency

When a worker misses heartbeats and is marked dead, its batch is re-enqueued
and a live worker will pick it up. The "dead" worker may still actually be
alive and finish the batch late — this creates a window where the same document
is processed twice. To prevent corrupt state:

- **Neo4j writes:** use `MERGE` on `(entity_name, entity_type, workspace_id)`.
  A second write of the same entity updates properties; it does not create a
  duplicate node. Relationship writes also use `MERGE` on the same key triple.
- **ChromaDB writes:** use `upsert` (not `add`). ChromaDB accepts an `ids`
  parameter; use `{workspace_id}:{source_url}:{chunk_index}` as the
  deterministic chunk ID. A second upsert of the same chunk is a no-op.
- **PostgreSQL job records:** use `UPDATE ingestion_jobs SET status = 'success'
  WHERE id = $1 AND status != 'success'` so a late worker cannot overwrite a
  completed record.

The coordinator itself is a single process with no failover in the local phase.
This is acceptable for local dev; a production deployment would need a
leader-election mechanism (e.g. etcd) — out of scope for this project.

### Local Dev Setup

All three components run as Docker containers on the same Docker network
(`kgre-net`), so they communicate over real TCP, not localhost IPC:

```
kgre-coordinator   port 50051 (gRPC)
kgre-worker-1      connects to coordinator:50051
kgre-worker-2      connects to coordinator:50051
kgre-worker-3      connects to coordinator:50051
```

Workers are identical images with different container names. Scale with
`docker compose scale worker=N`.

### Failure Test

Verify fault tolerance by running a large ingestion batch and then:
```
docker kill kgre-worker-1
```
Observe in the coordinator logs that the worker is marked dead after the
heartbeat timeout, and that another worker picks up the unfinished batch.
Verify no documents were double-written (check Neo4j node counts before vs.
after reassignment).

---

## Sharded Knowledge Graph (Phase 4)

Replaces the single Neo4j instance from Phases 1-3. The query interface
(Cypher) and graph data model do not change; only the physical layout changes.

### Why

A single Neo4j instance is both a throughput ceiling (one machine handles all
graph reads and writes) and a durability single point of failure. Sharding
splits the entity space across multiple instances. The trade-off: cross-shard
queries require a scatter-gather step, which adds latency and code complexity.
The benchmarking script (see below) produces real data to evaluate whether the
trade-off is worth it at your data scale.

### Consistent Hashing

All entities are assigned to a shard by hashing `sha256(entity_name.lower())`
and taking `hash % num_shards`. This gives:
- Deterministic assignment: the same entity always maps to the same shard.
- Even distribution: SHA-256 output is uniform, so shards hold roughly equal
  numbers of entities.
- Stable on reads: no routing table needs to be consulted at query time; any
  component can compute the shard from the entity name alone.

The shard count is set at init time (default: 3). Resharding (changing the
count) requires a migration script that moves entities to their new shard.
Do not change `num_shards` after data has been written.

### Shard Router

A thin Python layer (`backend/db/shard_router.py`) that wraps the Neo4j
drivers. The rest of the codebase calls the shard router instead of a Neo4j
driver directly.

**Single-entity lookup:**
```
1. Compute shard = sha256(entity_name.lower()) % num_shards
2. Query shard[shard] only
3. Return result
```

**Cross-shard relationship query (scatter-gather):**

This is the hard part. "How is Entity A connected to Entity B?" when A and B
hash to different shards:

```
1. Compute shard_a = sha256(A.lower()) % num_shards
2. Compute shard_b = sha256(B.lower()) % num_shards
3. If shard_a == shard_b: query that shard only, done.
4. Else: scatter
   a. Query shard_a for A's neighbors (one hop)
   b. Query shard_b for B's neighbors (one hop)
   c. Run both queries in parallel (asyncio.gather)
   d. Gather: find the intersection of A's neighbor set and B's neighbor set
      → these are the shared neighbors (two-hop paths)
   e. For deeper paths: repeat the scatter, expanding one hop at a time,
      until either the intersection is non-empty or max depth is reached.
5. Merge partial results into a combined path list.
6. Return to the query layer as if it came from a single Neo4j.
```

Edge case: an entity's relationships may span shards (e.g. Author A is on
Shard 0 but Paper P is on Shard 1). Cross-shard edges are stored on the shard
that owns the source entity, with a stub node on the target shard that stores
only the target entity's name and type (no full properties). The shard router
resolves stubs by fetching the full node from the owning shard.

### Local Dev Setup

Three Neo4j containers on the same Docker network:

```
kgre-neo4j-0   bolt://neo4j-0:7687   (Shard 0)
kgre-neo4j-1   bolt://neo4j-1:7688   (Shard 1)
kgre-neo4j-2   bolt://neo4j-2:7689   (Shard 2)
```

The shard router holds a connection pool to each. Writes during ingestion
route each entity to its owning shard. Reads during query route by entity name
or scatter-gather as needed.

### Benchmarking Script

`scripts/benchmark_sharding.py` compares:

| Query type                     | Single Neo4j | 2-shard | 3-shard |
|--------------------------------|--------------|---------|---------|
| Single-entity lookup (p50, ms) | 3.29         | 3.61    | 3.99    |
| Single-entity lookup (p99, ms) | 6.49         | 8.59    | 8.90    |
| Relationship query (p50, ms)   | 13.41        | 4.84    | 5.64    |
| Relationship query (p99, ms)   | 26.33        | 23.48   | 33.40   |
| Cross-shard fraction of rel Qs | N/A          | 50%     | 68%     |

Measured 2026-06-22 on the local 3-instance setup (`scripts/benchmark_sharding.py
--entities 300 --queries 200`), running shard counts 1/2/3 over the same three
Neo4j 5.18 instances (count 1 = single-node baseline).

Reading the numbers:
- **Single-entity lookups** get slightly slower per added shard (3.29 → 3.99 ms
  p50): one extra driver/connection hop, no scatter-gather. Negligible in
  absolute terms.
- **Relationship queries** are *faster* at p50 under sharding (13.4 → ~5 ms): each
  shard holds a third of the graph, so the local neighbour scan is cheaper, and
  the cross-shard scatter-gather runs the two halves in parallel. The p99 tail
  grows at 3-shard (33 ms) because the slowest scatter-gather waits on the
  slowest of more shards.
- **Ingestion throughput** is not graph-bound here — it is dominated by the
  per-document Gemini extraction latency (seconds), which dwarfs the sub-10 ms
  graph writes, so sharding does not move it. Not reported as a distinct row.

Conclusion at this scale (hundreds of entities): sharding is **not** worth the
operational/cost overhead — single-node latencies are already low. Sharding only
pays off once a single instance becomes a write/throughput or durability ceiling.
Re-run this benchmark at production scale before deciding (see AWS cost warning).

### AWS Cost Warning

On AWS, each Neo4j shard maps to a separate Neptune cluster. Neptune pricing
is per cluster-hour × instance size. Three clusters triple the database cost.
**Evaluate the benchmark results before deciding to shard in production.**
If query latency is acceptable on a single Neptune instance at your data scale,
keep it unsharded in the cloud phase and shard only if you hit a real ceiling.
This cost flag must be revisited explicitly in Phase 7.

---

## Tech Stack

### Local Development (current phase — use these)

| Component            | Local Tool                              | Introduced  | Notes                                              |
|----------------------|-----------------------------------------|-------------|----------------------------------------------------|
| Graph database       | Neo4j (Docker) × 1                      | Phase 1     | Single instance; sharded in Phase 4               |
| Graph database       | Neo4j (Docker) × 2-3                    | Phase 4     | Replaces single instance; shard router in front   |
| Vector store         | ChromaDB (Docker server)                | Phase 1     | Shared server (HttpClient) — API + worker are separate processes; in-process client is single-process only |
| Relational database  | PostgreSQL (Docker)                     | Phase 1     | User accounts, reports, workspaces                 |
| Cache                | Redis (Docker)                          | Phase 1     | Cache expensive graph traversals                   |
| Message queue        | Redis Queue (RQ)                        | Phase 1     | Simple queue; replaced by coordinator in Phase 3  |
| Worker orchestration | Custom coordinator + gRPC               | Phase 3     | Replaces RQ; see "Distributed Worker Pool"        |
| Worker transport     | gRPC (grpcio + grpcio-tools)            | Phase 3     | Coordinator ↔ worker RPC; proto in proto/          |
| LLM API              | Anthropic Claude API (claude-sonnet-4-6)| Phase 1     | Entity extraction, routing, synthesis              |
| Embedding model      | OpenAI text-embedding-3-small OR local sentence-transformers | Phase 1 | |
| Document ingestion   | Python scripts                          | Phase 1     | ArXiv API to start                                 |
| Backend API          | FastAPI (Python)                        | Phase 5     | REST API                                           |
| Frontend             | React + TypeScript                      | Phase 5     | Simple UI — query input + report viewer            |
| Background workers   | Docker containers (3×)                  | Phase 3     | Coordinator-managed; same Docker network           |

### Cloud Deployment (Phase 7 — do not build yet)

| Local Tool              | AWS Equivalent                                       |
|-------------------------|------------------------------------------------------|
| Neo4j (single)          | Amazon Neptune (single cluster)                      |
| Neo4j (sharded × 2-3)  | Amazon Neptune (multiple clusters — costly, see note)|
| ChromaDB                | Amazon OpenSearch                                    |
| PostgreSQL              | Amazon RDS                                           |
| Redis                   | Amazon ElastiCache                                   |
| Redis Queue             | Amazon SQS                                           |
| Coordinator container   | ECS Task (single; leader-election if HA needed)      |
| Worker containers       | ECS Tasks or EC2 instances (auto-scaled)             |
| FastAPI app             | Amazon ECS / Fargate                                 |
| File storage            | Amazon S3                                            |
| Auth                    | Amazon Cognito                                       |
| Orchestration           | AWS Step Functions                                   |

**Do not introduce AWS services until explicitly asked. Build locally first.**

---

## Data Models

### PostgreSQL (product data)

```sql
-- Organizations (multi-tenant isolation)
organizations (id, name, created_at)

-- Users
users (id, org_id, email, created_at)

-- Workspaces (a research project within a domain)
workspaces (id, org_id, name, domain, created_at)
-- domain is a free-text label the user sets, e.g.:
-- "AI/ML research", "climate policy", "macroeconomics",
-- "legal precedent", "materials science", "geopolitics"

-- Sources being ingested
sources (id, workspace_id, type, url, last_fetched, status, error_count)
-- type: "arxiv_feed", "rss", "pdf_upload", "web_url"

-- Background jobs
ingestion_jobs (id, source_id, document_url, status, error, created_at, completed_at)
-- Phase 3+: add assigned_worker_id, batch_id, heartbeat_at columns

-- Saved reports
reports (id, workspace_id, user_id, question, answer, retrieval_type, sources_used, version, created_at)
-- retrieval_type: "graph", "vector", "hybrid"
-- version: increments each time the same question is re-run
```

### Neo4j Graph (knowledge data)

```
Node labels:    Person, Organization, Paper, Concept, Event, Topic
                (domain-agnostic — "Concept" covers drugs, laws, algorithms,
                financial instruments, policies, technologies, etc.)
Edge types:     AUTHORED, CITED, FUNDED_BY, CONFLICTS_WITH,
                COLLABORATED_WITH, PUBLISHED_IN, SUPPORTS, CONTRADICTS

Node properties (all nodes): workspace_id, created_at, last_updated, source_count
Edge properties (all edges): source_document_id, confidence, created_at, workspace_id

Special: CONFLICTS_WITH edges are auto-created when two sources make
         contradictory claims about the same relationship

Phase 4+: each node also carries shard_id (int) for debugging/validation.
          Stub nodes on non-owning shards carry is_stub=true.
```

### ChromaDB Collections (vector data)

```
Collection per workspace: "workspace_{workspace_id}_chunks"

Each chunk document:
  - id: "{workspace_id}:{source_url}:{chunk_index}"   ← deterministic for idempotent upsert
  - text: the chunk content
  - metadata:
      source_url, source_title, source_date,
      chunk_index, workspace_id,
      entity_mentions: [list of entity names found in chunk]
```

---

## Ingestion Pipeline (detailed)

### Phases 1-2: Simple single-worker pipeline

One document flows through these steps:

```
1. Fetch document (HTTP request or PDF parse)
2. Clean and chunk text (~512 token chunks with 50 token overlap)
3. Parallel:
   a. Embed chunks → upsert into ChromaDB (deterministic chunk ID)
   b. LLM entity extraction:
        Prompt: "Extract all named entities and relationships from this text.
                 Return ONLY valid JSON: {entities: [...], relationships: [...]}
                 Entity fields: name, type, aliases[]
                 Relationship fields: source, target, type, context, confidence"
        → Parse JSON response
        → Entity resolution: merge with existing nodes (fuzzy name match)
        → MERGE nodes and edges into Neo4j (idempotent)
4. Mark ingestion_job as complete in PostgreSQL
```

### Phase 3+: Coordinator-managed pipeline

Same per-document steps, but the execution layer changes:

```
Coordinator assigns a batch of document URLs to a worker
Worker loops over the batch:
  For each document URL:
    → same steps 1-4 as above
    → send Heartbeat RPC after each document
Worker calls ReportCompletion when the batch is done
Coordinator updates ingestion_job records in PostgreSQL
```

Idempotency is required in both phases so that reassigned batches don't
double-write. See the "Distributed Worker Pool" section for the specific
MERGE / upsert patterns.

**Entity resolution rule:** If a new entity name has >0.85 cosine similarity
to an existing entity name (same type), treat as the same entity and merge
properties. Do not create duplicate nodes.

---

## Query Flow (detailed)

### Phases 1-2: Single Neo4j

```
1. Router LLM call:
   Prompt: "Classify this research question. Return JSON only:
            {type: 'graph'|'vector'|'hybrid', reasoning: '...'}"

2a. If graph:
    - LLM translates question to Cypher
    - Execute against the single Neo4j
    - Return: nodes, edges, paths, conflict flags

2b. If vector:
    - Embed the question
    - Query ChromaDB for top-k similar chunks
    - Return: chunks with source metadata

2c. If hybrid:
    - Run both 2a and 2b in parallel
    - Merge results

3. Synthesizer LLM call:
   - Input: structured results from step 2
   - Output: prose answer with inline citations
   - Constraint: ONLY cite facts that appear in the retrieved results

4. Save report to PostgreSQL (versioned)
5. Return to user
```

### Phase 4+: Shard router in the graph path

Step 2a changes:

```
2a. If graph:
    - LLM translates question to Cypher + extracts entity names mentioned
    - Shard router: for each entity, compute shard = sha256(name) % num_shards
    - If all entities on same shard: query that shard only
    - If entities span shards: scatter-gather
        → query each shard in parallel
        → merge partial results (intersect neighbor sets for path queries)
    - Return merged: nodes, edges, paths, conflict flags
```

---

## Starting Domain

**AI/ML research papers via ArXiv API.**

Why: Free API, well-documented, papers have clear entities (authors,
institutions, concepts, citations), and the builder knows the domain well
enough to evaluate output quality.

ArXiv API endpoint: `http://export.arxiv.org/api/query`
Start with categories: `cs.AI`, `cs.LG`, `cs.CL`
Fetch last 90 days of papers to seed the graph.

---

## Project Structure

```
/
├── CLAUDE.md                  ← You are here. Read this every session.
├── docker-compose.yml         ← Neo4j (×1 Phase 1-3, ×3 Phase 4+), PostgreSQL, Redis
│                                 coordinator, workers
├── .env                       ← API keys and config (never commit)
├── .env.example               ← Template for .env
│
├── proto/                     ← (Phase 3) gRPC service definitions
│   └── coordinator.proto      ← Register, RequestWork, Heartbeat, ReportCompletion, GetStatus
│
├── backend/
│   ├── main.py                ← FastAPI app entry point
│   ├── api/
│   │   ├── routes/
│   │   │   ├── questions.py   ← POST /question, GET /reports
│   │   │   ├── workspaces.py  ← CRUD for workspaces
│   │   │   └── sources.py     ← Add/remove ingestion sources
│   ├── core/
│   │   ├── router.py          ← Query type classifier
│   │   ├── graph_retriever.py ← Calls shard_router (Phase 4+) or neo4j directly
│   │   ├── vector_retriever.py← ChromaDB query logic
│   │   └── synthesizer.py     ← LLM answer generation
│   ├── ingestion/
│   │   ├── fetcher.py         ← Fetch documents from sources
│   │   ├── chunker.py         ← Split documents into chunks
│   │   ├── entity_extractor.py← LLM entity/relationship extraction
│   │   ├── entity_resolver.py ← Merge duplicate entities
│   │   └── worker.py          ← Phase 1-2: RQ worker; Phase 3+: gRPC worker client
│   ├── coordinator/           ← (Phase 3) Coordinator process
│   │   ├── server.py          ← gRPC server: Register, RequestWork, Heartbeat, ReportCompletion, GetStatus
│   │   ├── registry.py        ← In-memory worker registry + heartbeat monitor
│   │   ├── scheduler.py       ← Pulls pending sources from PostgreSQL, enqueues batches
│   │   ├── job_tracker.py     ← Durable ingestion_jobs/sources bookkeeping + source rollup
│   │   └── worker_client.py   ← gRPC worker client (Register/RequestWork/Heartbeat loop)
│   ├── db/
│   │   ├── postgres.py        ← SQLAlchemy models and session
│   │   ├── neo4j.py           ← Neo4j driver and query helpers (single-node)
│   │   ├── shard_router.py    ← (Phase 4) Consistent hash router across 2-3 Neo4j shards
│   │   ├── chroma.py          ← ChromaDB client and helpers
│   │   └── redis.py           ← Redis client and queue helpers
│   └── models/
│       └── schemas.py         ← Pydantic models
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── QuestionInput.tsx
│   │   │   ├── ReportViewer.tsx
│   │   │   └── GraphViewer.tsx  ← D3.js graph visualization (Phase 6)
│   │   └── App.tsx
│
└── scripts/
    ├── seed_arxiv.py          ← One-time script to seed graph from ArXiv
    └── benchmark_sharding.py  ← (Phase 4) Compare single-node vs. sharded query latency
```

---

## Build Phases

**Current state: Phases 1–6 complete. Phase 7 (AWS) not started.**

The full local system is built and tested: the single-worker pipeline and query
layer (Phases 1–2), the distributed coordinator/worker pool with durable job
tracking (Phase 3), the consistent-hash shard router on both the write and read
paths (Phase 4), the API + React UI (Phase 5), and the Phase 6 polish — graph
visualization, conflict detection surfaced in answers, source provenance,
multi-workspace support, and the coordinator dashboard. Sharding and the
distributed pool are opt-in (USE_SHARDING / the `distributed` compose profile)
with the single-node + single-RQ-worker path as the always-available fallback.

---

### Phase 1 — Local pipeline (single worker, single Neo4j)
*Get something simple end-to-end before adding complexity.*

- [x] docker-compose.yml with Neo4j, PostgreSQL, Redis
- [x] ArXiv fetcher script
- [x] Entity extractor (LLM → JSON → Neo4j)
- [x] ChromaDB embedding pipeline
- [x] Seed graph with 500 AI/ML papers
- [x] Verify graph has real nodes and edges

**Gate: do not start Phase 2 until the graph has real data and Neo4j queries
return correct nodes and relationships.**

---

### Phase 2 — Query layer (single worker, single Neo4j)
*Verify the simple version answers questions correctly before adding complexity.*

- [x] Query router (classify question type)
- [x] Graph retriever (Cypher queries for relationship questions)
- [x] Vector retriever (ChromaDB similarity search)
- [x] Synthesizer (LLM answer from structured results)
- [x] Test with 10 real questions, evaluate answer quality

**Gate: do not start Phase 3 until answers are demonstrably correct on the
simple single-worker, single-Neo4j setup.**

---

### Phase 3 — Distributed worker pool
*Replace the simple ingestion worker with the coordinator/worker architecture.
Built on top of the working Phase 1-2 pipeline — the per-document logic is
unchanged; only the execution layer changes.*

**Prerequisite: Phase 1 and Phase 2 gates passed.**

- [x] Define gRPC service in `proto/coordinator.proto`
  (Register, RequestWork, Heartbeat, ReportCompletion)
- [x] Generate Python stubs with `grpc_tools.protoc`
- [x] Implement coordinator server (`backend/coordinator/server.py`)
  - Worker registry with heartbeat tracking
  - Heartbeat timeout detection and worker death marking
  - Batch reassignment to live workers when a worker is marked dead
- [x] Implement worker gRPC client in `backend/ingestion/worker.py`
  - Register on startup, call RequestWork, send Heartbeats every 5 s,
    call ReportCompletion when batch is done
- [x] Update `ingestion_jobs` table: add `assigned_worker_id`, `batch_id`,
  `heartbeat_at` columns (safe migration in startup lifespan)
- [x] Update docker-compose.yml: coordinator container + 3 worker containers
  on shared `kgre-net` network
- [x] Make all Neo4j writes idempotent (MERGE instead of CREATE)
- [x] Make all ChromaDB writes idempotent (upsert with deterministic chunk IDs)
- [x] Failure test: kill a worker mid-batch, observe reassignment,
  verify no double-writes

---

### Phase 4 — Sharded knowledge graph
*Replace single Neo4j with 2-3 shards behind a consistent-hash router.
Implement scatter-gather for cross-shard queries. Run the benchmark.*

**Prerequisite: Phase 3 working and tested (so the distributed worker pool
can write to shards correctly).**

- [x] Add shard router (`backend/db/shard_router.py`)
  - Consistent hashing: `sha256(entity_name.lower()) % num_shards`
  - Connection pools for each shard
  - Single-shard query path
  - Scatter-gather path for cross-shard relationship queries
    (parallel query → merge neighbor sets → resolve stubs)
- [x] Update docker-compose.yml: 3 Neo4j containers (`neo4j-0/1/2`) on `kgre-net`
- [x] Update ingestion workers to route entity writes through the shard router
- [x] Update `graph_retriever.py` to use shard router instead of direct Neo4j driver
- [x] Add `shard_id` property to all Neo4j nodes; add stub node handling
- [x] Write `scripts/benchmark_sharding.py`:
  - Single-entity lookup latency (p50, p99) — single-node vs. 2-shard vs. 3-shard
  - Cross-shard relationship query latency (p50, p99)
  - Ingestion throughput (documents/second)
- [x] Run benchmark on the seeded ArXiv graph, fill in the results table above
- [x] Decide based on benchmark results whether sharding is worth keeping

---

### Phase 5 — API + basic UI
*Expose the pipeline through a web interface. This can be built in parallel
with Phase 3/4 since it wraps the same query layer without touching ingestion
or the graph internals.*

- [x] FastAPI app with /question and /reports endpoints (skeleton exists)
- [x] Simple React frontend (skeleton exists — question input + answer display)
- [x] PostgreSQL for saving reports (implemented)
- [x] Redis caching for repeated graph queries (implemented)
- [x] Streaming SSE endpoint for question progress (implemented)

---

### Phase 6 — Polish
- [x] Graph visualization (D3.js) showing entity relationships
- [x] Conflict detection and flagging in answers
- [x] Source provenance (every fact links to its source document)
- [x] Multi-workspace support
- [x] Coordinator dashboard (worker health, queue depth, batch progress)

---

### Phase 7 — AWS deployment
*Do not start until Phase 5 and 6 are complete and stable locally.*

- [ ] Migrate Neo4j → Neptune
  - **Cost warning:** if Phase 4 sharding is kept, each shard = one Neptune
    cluster. Three Neptune clusters are expensive. Re-evaluate benchmark
    results here. If single-node query latency is acceptable at production
    data scale, keep Neptune unsharded and skip multi-cluster setup.
- [ ] Migrate ChromaDB → Amazon OpenSearch
- [ ] Migrate PostgreSQL → Amazon RDS
- [ ] Migrate Redis → Amazon ElastiCache
- [ ] Coordinator → ECS Task (single task; add leader-election if HA needed)
- [ ] Workers → ECS Tasks or EC2 (auto-scaled)
- [ ] Deploy API → ECS/Fargate
- [ ] Add Cognito auth
- [ ] Migrate SQS as fallback job queue (if coordinator is unavailable)

---

### Phases 3 and 4 — built and verified

Both distributed phases are implemented end-to-end on top of the working
Phases 1–2 pipeline, with the single-node path preserved as the fallback.

**Phase 3 (distributed pool):** the coordinator runs a reaper *and* the
scheduler (`pull_pending_once`), so 'pending' sources are expanded into batches
and handed to workers. A `JobTracker` mirrors the in-memory registry into
Postgres — one `ingestion_jobs` row per document (deterministic uuid5 id),
queued→running→success/failed transitions, and a source rollup to a terminal
status — all with conditional, replay-safe writes. Covered by
`scripts/coordinator_test.py` (kill/reassign), `scripts/distributed_e2e_test.py`
(full coordination path), and `tests/test_job_tracker.py`.

**Phase 4 (sharding):** writes and reads both go through the shard router under
`USE_SHARDING=true`. `graph_retriever` scatter-gathers each read across all
shards and merges (de-duped), degree context is summed across shards, and
conflict detection runs shard-locally on the source entity's shard. Covered by
`scripts/shard_router_test.py` and `tests/test_shard_read.py`.

The deliberate ordering (simple first, distributed second) means there is
always a working fallback: if the coordinator has a bug, revert to the single
RQ worker; if the shard router has a bug, unset `USE_SHARDING` to point
`graph_retriever.py` back at the single Neo4j. Never let the distributed layer
be the only way to make the system work.

---

## Environment Variables (.env)

```
ANTHROPIC_API_KEY=
OPENAI_API_KEY=           # for embeddings (or use sentence-transformers)

# Phase 1-2: single Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=

# Phase 4+: sharded Neo4j (set NUM_SHARDS and one URI per shard)
NUM_SHARDS=3
NEO4J_SHARD_0_URI=bolt://neo4j-0:7687
NEO4J_SHARD_1_URI=bolt://neo4j-1:7688
NEO4J_SHARD_2_URI=bolt://neo4j-2:7689

# Phase 3+: coordinator
COORDINATOR_HOST=coordinator
COORDINATOR_PORT=50051

POSTGRES_URL=postgresql://user:password@localhost:5432/kgre
REDIS_URL=redis://localhost:6379

CHROMA_PERSIST_DIR=./chroma_data
```

---

## Key Decisions Already Made

- **Local first, AWS later.** Do not introduce cloud services until Phase 7.
- **Neo4j over Neptune locally.** Same Cypher query language, free, Docker.
- **ChromaDB over OpenSearch locally.** Simpler, same Docker workflow. Runs as a
  shared server (not in-process): the API and ingestion worker are separate
  processes and must read/write one Chroma server, or the worker's writes are
  invisible to the API. Connect via `chromadb.HttpClient` (`CHROMA_HOST`/`PORT`).
- **ArXiv as the starting domain.** Free API, well-structured data.
- **LLM is constrained.** It only extracts entities (JSON output) and
  synthesizes answers (from retrieved results). It never generates facts freely.
- **Dual retrieval with routing.** Graph for relationships, vector for knowledge,
  hybrid for mixed questions. Router is an LLM classifier.
- **Entity resolution is required.** Duplicate nodes break the graph.
  Fuzzy match on name + type before creating new nodes.
- **Reports are versioned.** Re-running the same question creates a new version,
  old ones are preserved.
- **Distributed complexity is layered on top of a working simple version.**
  The coordinator/worker pool (Phase 3) replaces RQ but keeps the per-document
  pipeline identical. The shard router (Phase 4) replaces the single Neo4j
  driver but keeps the Cypher queries identical. This means there is always
  a working simpler version to fall back to if the distributed layer breaks.
  Never let Phase 3 or 4 be the only path through the system before they are
  fully tested.
- **Idempotency is non-negotiable once Phase 3 is active.** Any document
  can be processed twice (due to worker reassignment). All writes must be safe
  to replay: MERGE in Neo4j, upsert in ChromaDB, conditional UPDATE in
  PostgreSQL.
- **Benchmark before committing to Neptune sharding.** Phase 4 produces real
  latency data. Use it to decide whether multi-cluster Neptune is worth the
  cost in Phase 7. Do not assume sharding is necessary at production scale
  until the numbers say so.

---

## What NOT to Do

- Do not use LangChain or LlamaIndex. Build the pipeline directly so the
  architecture is transparent and learnable.
- Do not skip entity resolution. Duplicate nodes make the graph useless.
- Do not let the LLM generate unsourced facts in answers. Every claim must
  trace to a retrieved document or graph result.
- Do not start Phase 3 before Phases 1 and 2 are verified working end-to-end.
- Do not start Phase 4 before Phase 3 is stable (workers, coordinator,
  heartbeat timeout, reassignment all tested).
- Do not introduce AWS services before Phase 7.
- Do not use CREATE in Neo4j for entity/relationship writes after Phase 3 —
  always MERGE.
- Do not change `NUM_SHARDS` after data has been written to the graph. If
  resharding is needed, write a migration script first.
