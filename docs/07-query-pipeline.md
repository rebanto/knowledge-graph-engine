# 07 — Query pipeline

The read path: turn a natural-language question into a sourced, structured
answer. Orchestrated by
[`qa_pipeline.answer_question`](../backend/core/qa_pipeline.py) (used by `POST
/question`) and mirrored inline in the SSE handler (`GET /question/stream`).

## Flow

```
question
   │
   ▼
classify_question (router.py, Gemini)  ─────► {type: graph|vector|hybrid}   [route cache 24h]
   │
   ├── type=graph  ─► run_graph_query
   ├── type=vector ─► run_vector_query
   └── type=hybrid ─► gather(graph, vector)   ← run in parallel
   │
   ▼
synthesize_answer (synthesizer.py, Gemini)  ─► {answer (markdown), key_entities, insights}
   │
   ▼
save Report (Postgres, versioned)  ─► QuestionResponse
```

Each stage degrades gracefully: if graph retrieval raises (unsafe Cypher or an
open circuit breaker) the vector results are still used, and vice versa. A
hybrid question with one failing retriever still returns an answer.

## Stage 1 — Routing

[`router.classify_question`](../backend/core/router.py) asks Gemini to classify
the question and returns `{type, reasoning}`:

- **`graph`** — relationships between named entities (who authored what, what
  connects X to Y, citation chains, "most cited", contradictions).
- **`vector`** — knowledge/content (summarize findings, latest developments,
  evidence for a claim, open problems).
- **`hybrid`** — needs both. **When in doubt, the prompt prefers hybrid**, since
  it runs both retrievers.

Unknown/invalid responses fall back to `hybrid`. The result is cached in Redis
for 24h (`route:<hash>`).

## Stage 2a — Graph retrieval

[`graph_retriever.run_graph_query`](../backend/core/graph_retriever.py):

1. **Question → Cypher.** Gemini is given the full graph `SCHEMA` and strict
   query-design guidelines, and must return `{"cypher": "MATCH …"}`. The prompt
   forces a `{workspace_id: "…"}` filter on **every** node pattern and named
   return columns (never whole nodes).
2. **Safety gate.** A regex blocklist rejects any query containing `CREATE`,
   `MERGE`, `DELETE`, `REMOVE`, `SET`, `DROP`, `DETACH`, `CALL`, `LOAD CSV`, or
   `FOREACH` → raises `UnsafeQueryError`. **Only read-only Cypher executes.**
3. **Cache.** The generated Cypher's result set is cached for 5 min
   (`cypher:<hash>`); a hit skips Neo4j entirely.
4. **Execute** against Neo4j (circuit-breaker-guarded, 15s timeout).
5. **Entity-degree context.** Entity-looking strings in the result are collected
   and a secondary query fetches each one's degree (connection count), giving the
   synthesizer a sense of which entities are hubs. Best-effort; failures ignored.

Returns `{cypher, records, entity_stats}`.

> **Under Phase 4 sharding** the execution layer changes (the graph retriever
> can route through the shard router's `find_connection` scatter-gather) but the
> Cypher generation and safety gate are unchanged. See [Sharding](10-sharding.md).

## Stage 2b — Vector retrieval

[`vector_retriever.run_vector_query`](../backend/core/vector_retriever.py):

1. **Embed the question** (`all-MiniLM-L6-v2`), with a 7-day Redis embedding
   cache (`embed:<hash>`) — the same text always embeds identically.
2. **Query** the workspace's ChromaDB collection for the top-k nearest chunks
   (default `top_k=8` in the pipeline). Empty collections are handled (Chroma
   raises if `n_results` exceeds the count, so it's clamped).
3. Return chunks as `{text, source_title, source_url, distance}`.

## Stage 3 — Synthesis

[`synthesizer.synthesize_answer`](../backend/core/synthesizer.py) turns the
**retrieved** data into the final answer. Gemini receives the question, the
retrieval type, and the JSON-serialized results (capped at **40,000 chars** —
the old 8k cap silently dropped most retrieved chunks before the model saw
them).

Output is structured JSON:

- **`answer`** — markdown. The prompt requires a direct 1–2 sentence opener,
  arrow-notation relationship chains (e.g. `**Hinton** → AUTHORED → *Deep
  Residual Learning*`), real numbers from the data, and explicit notes on any
  `conflict_flag=true` edges.
- **`key_entities`** — 2–6 `{name, type, role}` items.
- **`insights`** — 1–3 typed cards rendered by the frontend:
  `stat_grid`, `bar_chart`, `flow_path`, `comparison_table`, `timeline`.

**Hard grounding rule:** every entity, date, count, and relationship in the
answer **must** appear in the retrieved data. If data is sparse, the model is
told to write a short honest answer with a `stat_grid` of "Results Found: 0".

If the structured call yields no `answer`, a **plain-text fallback prompt**
produces a short prose answer (`generate_text`) with empty entities/insights.

`_clean_entities` / `_clean_insights` defensively validate and clamp every field
(lengths, numeric coercion, allowed insight types, max counts) so a malformed
LLM response can never produce a broken `QuestionResponse`.

## Why answers are never cached

[`qa_pipeline.answer_question`](../backend/core/qa_pipeline.py) **always
recomputes** the final answer (it only increments a cache-miss metric). A cached
answer captured before a newly-added source finished ingesting would silently
omit that source's content, making the engine look like it doesn't know about
data it actually holds. Route, Cypher, and embedding caches still apply — only
the final synthesis is always fresh. See [Caching](11-caching.md).

## The LLM client

All Gemini access goes through [`llm_client.py`](../backend/core/llm_client.py).
Key properties:

| Concern | How it's handled |
|---------|------------------|
| **Provider** | Google Gemini via `google-genai`. Model from `LLM_MODEL` (default `gemini-flash-lite-latest`). **Not Claude** despite `CLAUDE.md`. |
| **Sync→async bridge** | The SDK is synchronous; calls run in a dedicated `ThreadPoolExecutor(max_workers=8)` **bulkhead** so LLM I/O can't starve the DB thread pools. |
| **Timeouts** | `asyncio.wait_for` wraps every call (`LLM_CALL_TIMEOUT=90s`, OCR `180s`). The SDK has no built-in timeout; this converts a hung call into a normal failure so an ingestion job can still reach a terminal state. |
| **Retries** | Transient `ServerError` (429/503 bursts) retried up to 2× with exponential backoff + jitter, capped at 10s. |
| **Quota** | A `PerDay` `ClientError` becomes `DailyQuotaExhausted` → HTTP 503 + `Retry-After: 86400`. |
| **Circuit breaker** | The breaker is *checked* before each call but the real call is **deliberately not routed through it** — extraction fires many concurrent windows, so transient bursts would otherwise trip the breaker and cascade every in-flight document to failure. The per-call retry loop is the right granularity. |
| **Modes** | `generate_json` (forces `response_mime_type=application/json`), `generate_text`, `generate_text_stream` (SSE), `ocr_pdf` (multimodal). |

## Streaming (SSE)

`GET /api/question/stream` ([`questions.py`](../backend/api/routes/questions.py))
emits the same pipeline as named events so the UI shows progress:

| Event | Payload |
|-------|---------|
| `progress` | `{status: "Analyzing question…" / "Querying knowledge graph…" / "Searching documents…" / "Synthesizing answer…"}` |
| `routing` | `{type}` — emitted as soon as the route is known |
| `done` | the full `QuestionResponse` JSON (including the saved report id + version) |
| `error` | `{detail}` |

The frontend's [`streamQuestion`](../frontend/src/api.ts) consumes these and
**falls back to a plain `POST /question`** on a connection-level error, so the
user still gets an answer if streaming is unavailable.

Continue to [API reference](08-api-reference.md).
