# 08 — API reference

FastAPI app in [`backend/main.py`](../backend/main.py). All product routes are
under the **`/api`** prefix. Interactive OpenAPI docs are served at
`http://localhost:8000/docs`.

- **CORS:** any `http://localhost:*` / `http://127.0.0.1:*` origin.
- **Auth:** product routes under `/api` require a logged-in user, except the
  `/api/auth/*` entry points. The browser uses HttpOnly cookies; Bearer access
  tokens are also accepted for programmatic clients.
- **Rate limiting:** slowapi is wired up (`Limiter` keyed on authenticated user
  when available, otherwise remote address); the `RateLimitExceeded` handler
  returns 429.
- **Request IDs:** every response carries `X-Request-ID` (generated if absent),
  bound into the structlog context for the request.
- **Quota:** any `DailyQuotaExhausted` raised anywhere becomes **503** with
  `Retry-After: 86400`.

Pydantic request/response shapes live in
[`models/schemas.py`](../backend/models/schemas.py).

---

## Auth

### `POST /api/auth/register`
Create an account and auto-login. **Body:** `{email, password}` (password min
length 8). Sets `kgre_access` and `kgre_refresh` HttpOnly cookies. `409` if the
email is already registered; `403` if `REGISTRATION_ENABLED=false`.

### `POST /api/auth/login`
Login with `{email, password}`. Sets both auth cookies and returns
`{id, email, created_at}`. Unknown email and wrong password both return the same
generic `401`.

### `POST /api/auth/refresh`
Rotates the refresh token, issues fresh cookies, and returns the user. Reuse of a
revoked refresh token revokes the remaining token family and returns `401`.

### `POST /api/auth/logout`
Revokes the presented refresh token, clears both cookies, and returns `204`.

### `GET /api/auth/me`
Returns the current user from the access token cookie or Bearer token.

---

## Questions & reports

### `POST /api/question`
Ask a question (blocking; returns the full answer).

**Body** (`QuestionRequest`): `{ "question": str, "workspace_id": str = "arxiv_seed" }`

**Response** (`QuestionResponse`):
```jsonc
{
  "id": "uuid",
  "question": "…",
  "answer": "markdown…",
  "retrieval_type": "graph|vector|hybrid",
  "reasoning": "router's one-sentence justification",
  "cypher": "MATCH … | null",
  "graph_records": [ … ],
  "vector_chunks": [ {text, source_title, source_url, distance}, … ],
  "key_entities": [ {name, type, role}, … ],
  "insights": [ {type: "stat_grid|bar_chart|flow_path|comparison_table|timeline", …}, … ],
  "version": 1,
  "cached": false,
  "created_at": "ISO-8601"
}
```
The answer is also persisted as a `Report` with `version` = (count of prior
visible reports for this user+`question`+`workspace_id`) + 1.

### `GET /api/question/stream`
Server-Sent Events variant. **Query params:** `question` (required),
`workspace_id` (default `arxiv_seed`). Emits `progress`, `routing`, `done`,
`error` events (see [Query pipeline → Streaming](07-query-pipeline.md#streaming-sse)).
The `done` event's payload is the full `QuestionResponse` plus `id`/`version`/
`created_at`. The report is saved before `done` is emitted.

### `GET /api/reports`
List saved reports for a workspace (newest first, max 50). **Query:**
`workspace_id` (default `arxiv_seed`). Returns `ReportSummary[]`
(`{id, question, answer, retrieval_type, version, created_at}`). In the public
`arxiv_seed` workspace, users see their own reports plus legacy pre-auth rows.

### `GET /api/reports/{report_id}`
Full saved report rehydrated into a `QuestionResponse` (graph records, chunks,
entities, insights, cypher all restored from `sources_used`).

### `DELETE /api/reports/{report_id}`
Delete one report. `204`, or `404` if not found or not visible. A user can
delete their own report, or any report in a workspace they own.

---

## Workspaces

### `GET /api/workspaces`
Readable workspaces (oldest first): public NULL-owner demo workspaces plus the
current user's own workspaces. Returns `WorkspaceResponse[]`.

### `POST /api/workspaces`
Create. **Body** (`WorkspaceCreate`): `{name, domain, description?}`. The new
workspace is owned by the current user.

### `PUT /api/workspaces/{workspace_id}`
Update any of `{name?, domain?, description?}` (`WorkspaceUpdate`). Requires an
owned workspace; the public demo workspace returns `404`.

### `DELETE /api/workspaces/{workspace_id}`
Delete the workspace and **cascade** its sources, their ingestion jobs, and its
reports. `204`. (Note: this removes Postgres rows; orphaned graph/vector data is
reclaimed by the cleanup sweep.)
Requires an owned workspace.

### `POST /api/workspaces/{workspace_id}/discover`
Auto-discover sources from the workspace **description**. Gemini
([`source_discovery.py`](../backend/core/source_discovery.py)) maps the
description to 2–4 ArXiv category slugs; each new category becomes an
`arxiv_feed` source and is enqueued. Returns the created `SourceResponse[]`.
Requires an owned workspace; `400` if the workspace has no description; `422` if
no categories could be inferred.

---

## Sources

### `GET /api/workspaces/{workspace_id}/sources`
List sources (newest first). Also **auto-resets** any first-time source stuck in
`running` past 15 minutes to `error` (safety net for crashed workers without a
backend restart). Returns `SourceResponse[]`.

### `POST /api/workspaces/{workspace_id}/sources`
Add a source and enqueue ingestion (30-min job timeout). **Body**
(`SourceCreate`): `{type, url}` where `type ∈ {arxiv_feed, rss, web_url,
pdf_upload}`. For `arxiv_feed`, `url` may be a category, paper ID, arxiv URL, or
free-text query (see [Ingestion → Fetch](06-ingestion-pipeline.md#stage-1--fetch)).
Requires an owned workspace.

### `POST /api/workspaces/{workspace_id}/sources/upload`
Upload a PDF (multipart `file`). Saved under `uploads/` with a UUID-prefixed
name; a `pdf_upload` source is created and enqueued. Returns `SourceResponse`.
Requires an owned workspace.

### `GET /api/workspaces/{workspace_id}/sources/{source_id}/jobs`
Per-source ingestion-job summary. **Query:** `limit` (default 50). Returns
`SourceJobsResponse`: `{total, success, failed, running, jobs: IngestionJobBrief[]}`.

### `POST /api/workspaces/{workspace_id}/sources/{source_id}/retry`
Re-queue a source (sets `pending`, clears `last_error`). Skips already-processed
documents via the checkpoint. `404` if not found.
Requires an owned workspace.

### `POST /api/workspaces/{workspace_id}/sources/{source_id}/reingest`
**Force** a full re-ingest (`force=True`) — re-extracts and re-embeds even
already-processed documents (use after a pipeline change). Safe to replay
(MERGE + upsert).
Requires an owned workspace.

### `POST /api/workspaces/{workspace_id}/sources/reingest`
Force re-ingest of **every** source in the workspace. `404` if none.
Requires an owned workspace.

### `DELETE /api/workspaces/{workspace_id}/sources/{source_id}`
Delete a source and **precisely detach its contribution**: drops its `source_id`
from graph nodes/edges (deleting only what's now orphaned), deletes its vector
chunks (by `source_id` and URL), removes the PDF file, clears the checkpoint,
deletes its job rows, and invalidates workspace caches. Returns
`{status: "deleted", graph: {nodes_removed, edges_removed}}`. Shared concepts
that other live sources still assert are preserved.
Requires an owned workspace.

### `POST /api/workspaces/{workspace_id}/cleanup`
Reclaim stale data left by deleted sources and reset stuck-`running` sources past
15 min. Returns
`{stale_vector_sources_removed, stale_graph_papers_removed, orphaned_jobs_removed,
stuck_sources_reset}`. Safe to call anytime — only removes data with no active
source.
Requires an owned workspace.

---

## Graph & system

### `GET /api/graph`
Subgraph for visualization. **Query:** `workspace_id` (default `arxiv_seed`),
`limit` (default 150, max 500). Picks the highest-degree hub nodes and returns
every edge incident to those hubs (so hubs don't look disconnected from the
periphery). Returns `GraphResponse`:
`{nodes: [{name, type, degree}], edges: [{source, target, type, confidence, conflict}]}`.
See [`graph_explorer.py`](../backend/core/graph_explorer.py).

### `GET /api/system/queue`
RQ worker and queue health (drives the Sources UI worker indicator). Returns
`{worker_count, workers: [{name, state, queues, current_job_id}], queues:
{ingestion, ingestion_bulk, ingestion_dlq: {queued, started, failed}}}`. See
[`system.py`](../backend/api/routes/system.py).

### `GET /api/system/coordinator`
Distributed-worker coordinator status. Requires any authenticated user.

### `GET /api/system/mcp-config`
Returns a ready-to-paste local MCP stdio configuration for a readable workspace.
Requires auth; configs are only emitted for workspaces the current user can see.

---

## Operational endpoints (not under `/api`, hidden from schema)

| Endpoint | Purpose |
|----------|---------|
| `GET /health/live` | Liveness — process is up (`{status: "ok"}`). |
| `GET /health/ready` | Readiness — pings Postgres, Redis, Neo4j; `200` if all `ok`, else `503` with per-store status. |
| `GET /metrics` | Prometheus exposition (see [Observability](12-resilience-observability.md)). |
| `GET /docs`, `GET /openapi.json` | FastAPI interactive docs + schema. |

Continue to [Distributed worker pool](09-distributed-workers.md).
