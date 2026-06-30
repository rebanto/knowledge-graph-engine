# 13 — Frontend

A single-page **React 19 + TypeScript** app built with **Vite**, in
[`frontend/`](../frontend/). Styling is Tailwind (v4 via `@tailwindcss/postcss`);
charts use `recharts`; the graph visualization uses `d3`; markdown answers
render with `react-markdown`; icons are `lucide-react`.

## Running

`dev.ps1` launches it; or manually:

```bash
cd frontend
npm install        # or pnpm install
npm run dev        # vite dev server on :5173
npm run build      # tsc -b && vite build
npm run lint
```

In dev, the browser talks to the backend through **Vite's `/api` proxy** →
`http://127.0.0.1:8000` (see [`vite.config.ts`](../frontend/vite.config.ts)),
which keeps everything same-origin (no CORS) and — combined with the retrying
axios client — lets the UI survive a backend restart. Override the proxy target
with `VITE_PROXY_TARGET`, or bypass the proxy with `VITE_API_URL`.

## Layout & state

[`App.tsx`](../frontend/src/App.tsx) is the shell. Top-level state: the list of
workspaces and the current `workspaceId` (defaults to `arxiv_seed`), the active
tab, the report list, the active answer, loading/streaming/error flags, and
source counts. Three user-facing tabs:

| Tab | Component | Purpose |
|-----|-----------|---------|
| **Ask** | `QuestionInput` + `WorkspacePulse` + `AnswerView` | Ask a question, choose proof/trace/audit research moves, watch streamed progress, read the answer + proof/evidence strip. |
| **Explore** | `GraphViewer` | Interactive D3 force-directed view of the workspace's entity graph. |
| **Sources** | `SourceManager` / `SourcesPanel` | Add/upload/retry/delete sources, watch ingestion status, see worker/queue health. |

Sources are **polled** while any are `pending`/`running` so the UI reflects
ingestion progress live (`sourcePollRef`).

## The API client

[`src/api.ts`](../frontend/src/api.ts) — a typed axios client (45s timeout) with
**`axios-retry`** (3 retries, exponential backoff, on network errors and 5xx).
It exposes one function per backend endpoint (`askQuestion`, `listReports`,
`getReport`, `getGraph`, workspace CRUD, source CRUD/upload/retry,
`getQueueStatus`, `cleanupWorkspace`, `discoverSources`, …).

### Streaming with fallback

`streamQuestion(question, workspaceId, callbacks)` opens an `EventSource` against
`GET /api/question/stream` and wires `onRouting / onProgress / onDone / onError`.
Two subtleties it handles:

- It ignores the connection-close "error" that fires *after* a successful `done`
  (tracked via a `finished` flag).
- On a **connection-level** failure (backend down, no payload) it transparently
  **falls back to a plain `POST /api/question`**, so the user still gets an
  answer when SSE isn't available.

It returns a cancel function (used to abort an in-flight stream when the user
navigates away or asks again).

## Components

| Component | Role |
|-----------|------|
| `Sidebar` | Workspace selector + saved-report history; create/delete workspaces. |
| `QuestionInput` | The question box; submit triggers the stream. |
| `WorkspacePulse` | Workspace cockpit: source readiness, corpus mix, saved thread count, graph availability, and specialty prompt cards (`Proof Brief`, `Connection Trace`, `Disagreement Audit`, `Agent Context Pack`). |
| `AnswerView` | Renders the markdown answer, the `RoutingBadge`, `EntitySummary`, `ClaimLedger`, and `InsightCards`. |
| `AnswerProofBar` | Evidence strip for each answer: trust score, graph/passages/conflicts plus copy and Markdown export. |
| `ClaimLedger` | Claim-level verifier output: factual claims marked supported/unsupported so the trust score is inspectable. |
| `RoutingBadge` | Shows whether the question was routed graph / vector / hybrid. |
| `EntitySummary` | The `key_entities` list with type + role. |
| `InsightCards` | Renders the typed insight cards (`stat_grid`, `bar_chart` via recharts, `flow_path`, `comparison_table`, `timeline`). |
| `GraphViewer` | D3 force-directed graph from `GET /api/graph`; nodes colored by type, edges labeled by relation, conflict edges highlighted. |
| `SourceManager` / `SourcesPanel` | Source CRUD, PDF upload, per-source job drill-down, worker/queue status. |
| `WorkspaceSelector` | Workspace dropdown + create. |
| `EmptyState` | First-run / no-data guidance. |
| `ErrorBoundary` | Catches render errors so one bad component doesn't blank the app. |

## Types

[`src/types.ts`](../frontend/src/types.ts) mirrors the backend Pydantic schemas:
`QuestionResponse`, `ReportSummary`, the `Insight` union (matching the five
synthesizer insight types), `GraphData`/`GraphNode`/`GraphEdge`, `Workspace`,
`Source`/`SourceStatus`/`SourceType`, `IngestionJob`, and `QueueStatus`. Keeping
these in sync with `models/schemas.py` is the contract between the two halves.

Continue to [Scripts](14-scripts.md).
