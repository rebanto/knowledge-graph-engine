# 05 — Data models

The system has four stores. Each owns a distinct slice of state.

| Store | Owns | Source of truth for |
|-------|------|---------------------|
| **PostgreSQL** | product data | workspaces, sources, ingestion jobs, reports |
| **Neo4j** | knowledge graph | entities + relationships + source attribution |
| **ChromaDB** | vector index | document chunks + embeddings + metadata |
| **Redis** | ephemeral | caches, ingestion checkpoints, resolver registry, the RQ queue |

PostgreSQL is the **product source of truth**: deleting a source there triggers
precise cleanup of the corresponding graph + vector data.

---

## PostgreSQL

SQLAlchemy models in [`backend/db/models.py`](../backend/db/models.py). Tables
are created on startup (`Base.metadata.create_all`) and patched by **idempotent
safe migrations** in the lifespan ([`main.py`](../backend/main.py)): `ADD COLUMN
IF NOT EXISTS`, plus a one-time `TIMESTAMP → TIMESTAMPTZ` upgrade for older DBs.

### `workspaces`

| Column | Type | Notes |
|--------|------|-------|
| `id` | String PK | `arxiv_seed` is the auto-seeded default workspace. |
| `name` | String | Display name. |
| `domain` | String | Free-text domain label (e.g. "AI/ML research"). |
| `description` | Text (nullable) | Used by source auto-discovery; added via safe migration. |
| `created_at` | TIMESTAMPTZ | |

### `sources`

| Column | Type | Notes |
|--------|------|-------|
| `id` | String PK | |
| `workspace_id` | String (indexed) | |
| `type` | String | `arxiv_feed` \| `rss` \| `web_url` \| `pdf_upload` |
| `url` | Text | For `arxiv_feed`, may be a category / paper ID / arxiv URL / free-text query, **not necessarily a URL**. For `pdf_upload`, the server-side file path. |
| `status` | String | `pending → running → success` \| `error` |
| `error_count` | Integer | Increments on each failure. |
| `last_error` | Text (nullable) | Human-readable last failure. |
| `last_fetched` | TIMESTAMPTZ (nullable) | Set on a completed run. |
| `created_at` | TIMESTAMPTZ | |

The **status lifecycle** is load-bearing — see
[Operations → the stuck-source story](15-operations.md#the-stuck-source-story).

### `ingestion_jobs`

One row per document processed within a source's ingestion run.

| Column | Type | Notes |
|--------|------|-------|
| `id` | String PK | |
| `source_id` | String (indexed) | |
| `document_url` | Text (nullable) | The specific document. |
| `status` | String | `queued → running → success` \| `failed` |
| `error` | Text (nullable) | |
| `created_at` / `completed_at` | TIMESTAMPTZ | |
| `assigned_worker_id` | String (nullable) | **Phase 3** bookkeeping; unused on the RQ path. |
| `batch_id` | String (nullable) | **Phase 3.** |
| `heartbeat_at` | TIMESTAMPTZ (nullable) | **Phase 3.** |

### `reports`

A saved, **versioned** answer.

| Column | Type | Notes |
|--------|------|-------|
| `id` | String PK | |
| `workspace_id` | String (indexed) | |
| `question` | Text | |
| `answer` | Text | Markdown. |
| `retrieval_type` | String | `graph` \| `vector` \| `hybrid` |
| `reasoning` | Text (nullable) | The router's one-sentence justification. |
| `sources_used` | JSONB | `{cypher, graph_records, vector_chunks, key_entities, insights}` — the full retrieval payload, so a report renders identically when re-opened. |
| `version` | Integer | Incremented each time the **same question** is re-run in the **same workspace** (count of prior reports + 1). |
| `created_at` | TIMESTAMPTZ (indexed) | |

---

## Neo4j graph schema

Write helpers in [`backend/db/neo4j.py`](../backend/db/neo4j.py) (single-node)
and [`shard_router.py`](../backend/db/shard_router.py) (Phase 4). The full schema
the LLM is shown when generating Cypher lives in the `SCHEMA` constant of
[`graph_retriever.py`](../backend/core/graph_retriever.py).

### Node labels

`Person`, `Organization`, `Paper`, `Concept`, `Event`, `Topic`.

`Concept` is the workhorse — algorithms, methods, architectures, datasets,
benchmarks, metrics, techniques, theorems. The extractor is told to emit these
aggressively because **shared concepts are what connect papers to each other**.

### Node properties

| Property | On | Meaning |
|----------|----|---------|
| `name` | all | The entity name (the merge key for non-Paper nodes). |
| `arxiv_id` | Paper | The merge key for papers (unique constraint). |
| `workspace_id` | all | Tenancy scope. Every read filters on this. |
| `source_count` | all | Number of distinct contributing sources (size of `source_ids`). |
| `source_ids` | all | **List** of Postgres source ids that asserted this node. Drives precise deletion. |
| `created_at` / `last_updated` | all | Neo4j `timestamp()`. |
| `entities_extracted` | Paper | `true` once extraction completed (the global "processed" flag). |
| `url`, `published`, `categories` | Paper | Document metadata. |
| `shard_id` | all (Phase 4) | Which shard owns this node. |
| `is_stub` | Phase 4 | `true` on a lightweight stand-in for a cross-shard target. |

### Relationship (edge) types

| Group | Types |
|-------|-------|
| Authorship / citation / people | `AUTHORED` (Person→Paper), `CITED` (Paper→Paper), `COLLABORATED_WITH` (Person→Person) |
| Affiliation / funding | `AFFILIATED_WITH` (Person/Paper→Organization), `FUNDED_BY` (Org→Org) |
| Paper ↔ content (connects papers) | `ABOUT` (Paper→Topic), `MENTIONS` (Paper→Concept), `PRESENTED_AT` (Paper→Event), `PUBLISHED_IN` |
| Conceptual structure | `USES`, `PROPOSES`, `EXTENDS`, `IMPROVES`, `COMPARED_TO`, `EVALUATED_ON`, `APPLIED_TO`, `PART_OF`, `RELATED_TO` |
| Claims | `SUPPORTS`, `CONTRADICTS`, `CONFLICTS_WITH` |

`CONFLICTS_WITH` is **auto-created** when two different source documents make
opposing `SUPPORTS`/`CONTRADICTS` claims about the same pair of entities — see
[Ingestion → Conflict detection](06-ingestion-pipeline.md#conflict-detection).

### Edge properties

| Property | Meaning |
|----------|---------|
| `source_document_id` | The document (arxiv_id/doc_id) that produced this edge. |
| `confidence` | `0.0–1.0`. Structured edges (authorship, category) are `1.0`; extracted concept edges carry the LLM's confidence (default `0.9`/`0.8`). |
| `workspace_id` | Tenancy scope. |
| `source_ids` / `source_count` | Same source-attribution list as nodes. |
| `context` | One-sentence justification from the extractor (≤500 chars). |
| `conflict_flag` | `true` on a `SUPPORTS`/`CONTRADICTS` edge that is disputed. |
| `created_at` / `last_updated` | |

### How a Paper is wired up

When a document is ingested ([`worker.process_document`](../backend/ingestion/worker.py)):

```
(Paper)-[:AUTHORED]-(Person)         ← from structured metadata (no LLM)
(Paper)-[:ABOUT]->(Topic)            ← from arxiv categories (no LLM)
(Paper)-[:MENTIONS]->(Concept)       ← extracted entities (LLM)
(Paper)-[:AFFILIATED_WITH]->(Org)    ← extracted entities (LLM)
(Paper)-[:PRESENTED_AT]->(Event)     ← extracted entities (LLM)
(Concept)-[:USES|PROPOSES|…]->(Concept)  ← extracted relationships (LLM)
```

Two papers covering the same concept become connected through it:
`(Paper A)-[:MENTIONS]->(Concept X)<-[:MENTIONS]-(Paper B)`. This is the
backbone of inter-paper structure and the reason concepts are extracted
aggressively.

### Constraints

Uniqueness constraints are created by `setup_constraints()` (called by the seed
script and the sharded setup): `Paper.arxiv_id`, and `name` on `Person`,
`Organization`, `Concept`, `Topic`, `Event`.

---

## ChromaDB collections

One collection per workspace: **`workspace_{workspace_id}_chunks`**, cosine
space (`hnsw:space: cosine`). Managed in [`backend/db/chroma.py`](../backend/db/chroma.py).
Embeddings are produced **locally** by `sentence-transformers` `all-MiniLM-L6-v2`
(384-dim) — no embedding API is called.

Each chunk:

```
id:    "{workspace_id}:{source_url}:{chunk_index}"   ← deterministic → idempotent upsert
text:  the chunk content (~400 words / ~512 tokens, 40-word overlap)
metadata:
  source_url     the document URL (or doc_id fallback)
  source_title   document title
  source_date    published date (may be "")
  chunk_index    int
  workspace_id   tenancy scope
  source_id      Postgres source id → enables precise deletion by source
```

Writes use **`upsert`** (not `add`) so reprocessing a document is a no-op rather
than a duplicate-ID crash. A re-ingest first `delete`s the document's prior
chunks (handles content shrinking or ID-format changes), then upserts the fresh
set.

---

## Redis key layout

[`backend/db/redis.py`](../backend/db/redis.py). Cache keys are
`namespace:sha256(normalized parts)`; operational keys use readable prefixes.

| Key pattern | Type | TTL | Purpose |
|-------------|------|-----|---------|
| `route:<hash>` | string (JSON) | 24h | Cached route classification. |
| `cypher:<hash>` | string (JSON) | 5 min | Cached Cypher result set. |
| `embed:<hash>` | string (base64 f32) | 7 days | Cached question embedding. |
| `qa:<hash>` | string (JSON) | 1h | Legacy answer cache — **written nowhere now**, swept on invalidation. |
| `inflight:<hash>` | string | 60s | In-flight request dedup lock (helpers present). |
| `resolver:<ws>:<type>` | hash | 30 days | Entity-resolver embeddings per workspace+type (cross-source dedup). |
| `checkpoint:<source_id>` | string | 7 days | Last processed document URL, for crash-resume mid-source. |
| RQ internal keys | — | — | The `ingestion`, `ingestion_bulk`, `ingestion_dlq` queues. |

`invalidate_workspace_caches()` SCANs and deletes `route:*`, `cypher:*`, `qa:*`
after a successful ingestion or a source deletion, so stale routes/queries are
never served. (It uses `SCAN`, not `KEYS`, to avoid blocking Redis.)

Continue to [Ingestion pipeline](06-ingestion-pipeline.md).
