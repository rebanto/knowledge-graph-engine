# 06 — Ingestion pipeline

The write path: turn a *source* into graph nodes/edges and vector chunks. The
per-document logic is identical whether it runs in the default RQ worker or the
Phase 3 distributed pool, and whether it writes to a single Neo4j or through the
shard router.

## End-to-end flow

```
add source (API)  →  Postgres source row (status=pending)  →  RQ enqueue
                                                                  │
                                          run_ingestion_job(source_id)   (RQ worker)
                                                                  │
                                            asyncio.run(_run_and_cleanup)
                                                                  │
   ┌──────────────────────────────────────────────────────────────────────────┐
   │ _run_async:                                                                │
   │   source.status = running                                                  │
   │   documents = fetch_documents_for_source(source)   ── dispatcher → fetcher │
   │   if 0 docs → status=error (no silent black hole)                          │
   │   filter out already-checkpointed docs (unless force)                      │
   │   resolver = EntityResolver(); load_from_redis()                           │
   │   gather over docs (Semaphore=5):                                          │
   │        process_document(doc, ws, resolver, source_id)                      │
   │        set_checkpoint(doc.url)                                             │
   │        write IngestionJob row (success/failed)                            │
   │   resolver.flush_to_redis(); clear_checkpoint(); invalidate caches         │
   │   status = success  (or error if every doc failed)                         │
   └──────────────────────────────────────────────────────────────────────────┘
                                                                  │
                                       finally: dispose ALL global async pools
```

Code: [`jobs.py`](../backend/ingestion/jobs.py) (orchestration) →
[`worker.py`](../backend/ingestion/worker.py) (`process_document`).

## Stage 1 — Fetch

[`dispatcher.fetch_documents_for_source`](../backend/ingestion/dispatcher.py)
maps `source.type` to a fetcher. Each fetcher returns a list of normalized
document dicts: `{id, title, text, authors, categories, url, published}`.

| Type | Fetcher | Behaviour |
|------|---------|-----------|
| `arxiv_feed` | [`fetchers/arxiv.py`](../backend/ingestion/fetchers/arxiv.py) | The `url` field is interpreted: explicit paper **IDs**/arxiv URLs (exact fetch, no date filter), **category** codes (`cs.AI`, date-filtered to last 90 days, newest first), or **free-text keyword** (relevance-sorted). Empty/garbage → default categories `cs.AI, cs.LG, cs.CL`. An ID lookup returning nothing **raises** (so the source shows a failure, not "0 docs / success"). TLS verified against certifi's CA bundle (Windows OS store is often stale). |
| `rss` | [`fetchers/rss.py`](../backend/ingestion/fetchers/rss.py) | Parses an RSS/Atom feed into documents. |
| `web_url` | [`fetchers/web.py`](../backend/ingestion/fetchers/web.py) | Fetches the page, strips `script/style/nav/footer/header/aside`, keeps full visible text. `doc_id = sha256(url)[:16]`. |
| `pdf_upload` | [`fetchers/pdf.py`](../backend/ingestion/fetchers/pdf.py) | Extracts the PDF text layer with `pypdf`. If <20 chars come out, the PDF is likely scanned/image-only → falls back to **Gemini multimodal OCR** (`ocr_pdf`), keeping whichever yields more text. Truly empty (no layer + OCR found nothing) raises. |

A fetch raising, or returning zero documents, sets `source.status = error` with
a descriptive `last_error` — never a misleading success.

## Stage 2 — Per-document processing

[`worker.process_document`](../backend/ingestion/worker.py) for one document:

1. **Skip check (per-workspace).** If `not force` and this workspace's ChromaDB
   collection already has chunks for the document, return `False` (skip). This
   is keyed on the **workspace's vector store**, *not* the global Neo4j
   `entities_extracted` flag — because Paper nodes are keyed by `arxiv_id` across
   all workspaces, using the global flag caused a document ingested in workspace
   A to be skipped in workspace B, leaving B green-but-empty. (Documented in
   project memory; this is the corrected behaviour.)
2. **Paper node** — `MERGE` on `arxiv_id` with url/published/categories.
3. **Authors** — for each author, resolve to a canonical name, `MERGE` a
   `Person`, and `MERGE (Person)-[:AUTHORED]->(Paper)` (confidence 1.0, no LLM).
4. **Categories → Topics** — `MERGE` a `Topic` per arxiv category and
   `(Paper)-[:ABOUT]->(Topic)` (confidence 1.0, no LLM). This connects every
   paper sharing a category.
5. **Embed + extract in parallel** (`asyncio.gather`):
   - **Embed:** chunk the body, delete any prior chunks for this document, upsert
     the fresh chunk set into ChromaDB with deterministic IDs.
   - **Extract:** windowed LLM entity/relationship extraction (see below).
6. **Extracted entities → nodes + Paper links.** Each entity is resolved to a
   canonical name, `MERGE`d as its label, and linked to the Paper via the
   type-appropriate edge (`Concept`→`MENTIONS`, `Topic`→`ABOUT`,
   `Organization`→`AFFILIATED_WITH`, `Event`→`PRESENTED_AT`; `Person`/`Paper`
   skipped — people come via `AUTHORED`).
7. **Extracted relationships → edges.** Only when **both** endpoints were
   extracted as entities. Edge carries `source_document_id`, `confidence`,
   `context`.
8. **Conflict detection** for `SUPPORTS`/`CONTRADICTS` edges (single-node only;
   skipped under sharding because endpoints may live on different shards).
9. **Mark processed** — set `Paper.entities_extracted = true`.

The graph backend (`_graph()`) is `shard_router` when `USE_SHARDING=true`, else
the single-node `neo4j` module; both expose the same surface.

## Chunking

[`chunker.chunk_text`](../backend/ingestion/chunker.py): word-count windows of
**400 words** (~512 tokens) with **40-word overlap**. Documents ≤400 words are a
single chunk. The body chunked is `"{title}. {text}"`.

## Entity extraction (windowed)

[`entity_extractor.extract_entities`](../backend/ingestion/entity_extractor.py)
covers the **whole document**, not just the abstract:

- Split into overlapping **6000-char windows** (600-char overlap), capped at
  **15 windows** (~90k chars) so a pathological file can't fan out into hundreds
  of calls. The document passed in is itself capped at 40,000 chars upstream.
- Each window → one Gemini JSON call; up to **4 windows run concurrently**.
- Per-window results are **merged and de-duplicated**: entities by
  `(name.lower(), type)` (aliases merged), relationships by
  `(source.lower(), target.lower(), type)` keeping the highest confidence.
- Only valid entity types (`Person/Organization/Paper/Concept/Event/Topic`) and
  valid edge types are kept; a relationship is dropped unless both endpoints
  also appear as entities, and confidence <0.7 is omitted by the prompt.

The prompt deliberately **prioritizes relationships** ("a document with 8
entities should usually yield 6+ relationships") — a graph of only authorship is
useless; the value is in the conceptual structure connecting documents.

## Entity resolution (cross-source dedup)

[`entity_resolver.EntityResolver`](../backend/ingestion/entity_resolver.py)
prevents duplicate nodes for the same real-world entity referred to slightly
differently across sources:

- The embedded key is **context-aware**: `name | type: <type> | aka <aliases>`
  rather than the bare name, so same-spelling/different-kind collisions ("BERT"
  the model vs "Bert" the person) are pushed apart and known aliases are pulled
  together. Cosine similarity is computed against the per-type registry.
- **Two decision paths:**
  - `resolve(name, type)` — synchronous, single-threshold (≥ `0.85` merges).
    Used for LLM-free structured names (authors) and the offline seed script.
  - `resolve_async(name, type, aliases, context)` — **three-band**, used for
    LLM-extracted entities (the ones that actually collide):
    - cosine ≥ `ENTITY_RESOLVE_HIGH` (0.97) → **auto-merge** (near-identical only);
    - cosine < `ENTITY_RESOLVE_LOW` (0.55) → **new entity**;
    - in between → **LLM adjudication** (`_adjudicate_same`): a cheap yes/no on
      whether the two names denote the same entity. The borderline band is
      exactly where a fixed threshold guesses wrong in both directions (false
      merges collapse distinct entities; false splits duplicate them). Fails
      closed (no merge) on error.
- The registry is **seeded from Redis** at job start (`load_from_redis`) and
  **flushed back** at job end (`flush_to_redis`), keyed `resolver:<ws>:<type>`,
  so dedup spans multiple sources and survives worker restarts (30-day TTL).
- Resolution quality is **measured**: `decide_pair` runs the same banding against
  labeled pairs in the quality benchmark, reporting precision/recall/F1 — see
  [Evaluation](18-evaluation.md).

## Idempotency

Any document can be processed twice (manual re-ingest, Phase-3 worker
reassignment, a late "dead" worker finishing). Every write is **replay-safe**:

| Store | Mechanism |
|-------|-----------|
| **Neo4j** | `MERGE` on `arxiv_id` (Paper) or `name` (others); edges `MERGE`d on the pair. `ON CREATE`/`ON MATCH` update props without duplicating. Source ids appended idempotently (`$source_id IN coalesce(n.source_ids, [])` guard). |
| **ChromaDB** | `upsert` with deterministic IDs `{ws}:{source_url}:{chunk_index}`; a second upsert of the same chunk is a no-op. |
| **PostgreSQL** | Job rows updated in place; the plan's conditional `UPDATE … WHERE status != 'success'` pattern protects against a late worker overwriting a completed record. |

## Conflict detection

[`conflict_detector.check_and_flag_conflict`](../backend/ingestion/conflict_detector.py):
when a `SUPPORTS` (or `CONTRADICTS`) edge is written between A and B, it looks
for an existing **opposite** edge between the same pair from a **different**
source document. If found:

- Both edges get `conflict_flag = true`.
- A `(A)-[:CONFLICTS_WITH]->(B)` edge is `MERGE`d.

This runs inline during ingestion (single-node only). A retroactive bulk pass
over a whole workspace is available via `detect_all_conflicts()` and the
[`scripts/detect_conflicts.py`](../scripts/detect_conflicts.py) script. Conflict
flags surface in answers and in the GraphViewer.

## Concurrency, retries, dead-letter queue

- **Per-source concurrency:** documents processed with `asyncio.Semaphore(5)`.
- **Per-document failure** is caught; the document's job row is marked `failed`
  and the failure is pushed to the **`ingestion_dlq`** queue for manual
  inspection/replay. One bad document does not fail the source.
- **Source-level outcome:** `success` normally; `error` if **every** document
  failed (`succeeded == 0`), so a fully-failed source never shows green.
- **Checkpointing:** after each successful document, `checkpoint:<source_id>` is
  set to its URL (7-day TTL). On a crash-and-restart mid-source, already-done
  documents are skipped up to the checkpoint (ignored on a `force` re-ingest).

## The event-loop disposal rule

This is the single most important operational invariant of the worker. Because
the RQ `SimpleWorker` runs **one `asyncio.run()` per job** (new event loop each
time), and the async DB pools (SQLAlchemy, Neo4j, redis.asyncio, shard router)
bind to the loop that created them, **every job must dispose all global async
pools before its loop closes**, or the *next* job dies with `RuntimeError: Event
loop is closed`.

[`_run_and_cleanup`](../backend/ingestion/jobs.py) wraps the job and calls
`_shutdown_async_resources()` in a `finally`, disposing the SQLAlchemy engine,
Neo4j driver, shard router, and Redis client — each guarded independently. A
regression repro lives at
[`scripts/repro_event_loop_disposal.py`](../scripts/repro_event_loop_disposal.py).

> Failure signature if this breaks: the symptom often appears **late** (Postgres
> `pool_pre_ping` transparently recovers, so the crash surfaces at the Redis
> flush) leaving `source.status` stuck at `running`. The startup recovery and
> the "stuck source" sweeps are the safety nets — see
> [Operations](15-operations.md).

## Source deletion & cleanup

Because every node/edge/chunk records the source(s) that asserted it, deletion
is **precise**:

- `DELETE /workspaces/{ws}/sources/{id}` →
  [`neo4j.remove_source_from_graph`](../backend/db/neo4j.py): drops this
  `source_id` from each node/edge's `source_ids`, then deletes only those left
  with **no remaining source** (shared concepts other live sources still assert
  are preserved). ChromaDB chunks deleted by `source_id` (and by URL for legacy
  chunks). The PDF file is removed; the Redis checkpoint cleared; caches
  invalidated.
- `POST /workspaces/{ws}/cleanup` → sweeps **orphaned** data (graph papers and
  vector chunks whose `source_id` no longer exists in `sources`) and resets
  sources stuck in `running` past the 15-minute threshold.

Continue to [Query pipeline](07-query-pipeline.md).
