# Lattice — frontend

The web interface for the Knowledge Graph Research Engine: ask a question,
watch it get routed to the graph or the documents (or both), and read an
answer that traces every claim back to a source.

React + TypeScript + Vite, Tailwind v4, D3 for the graph canvas, Recharts
for insight charts, `lucide-react` for icons. No component library — the UI
is hand-built in one consistent idiom.

## Design

The visual language ("warm ink + brass", Fraunces serif display, an
editorial drop-cap, eyebrow labels, a graph-paper texture) is documented in
[`DESIGN.md`](./DESIGN.md). All tokens live in `src/index.css` under
`@theme`. Reach for the existing utilities before inventing new colours.

## Develop

```bash
npm install
npm run dev      # Vite dev server on :5173, proxies /api to the backend
```

Point the proxy at a non-default backend with `VITE_PROXY_TARGET`
(see `vite.config.ts`). The retrying axios client survives a backend
restart without a page reload.

```bash
npm run build    # tsc -b && vite build
npm run lint     # eslint
```

## Layout

```
src/
├── App.tsx              app shell, tab nav, the Ask view
├── api.ts               axios client + endpoints (with retry)
├── index.css            the theme — design tokens and base styles
├── components/
│   ├── Sidebar          wordmark, workspace switcher, question history
│   ├── QuestionInput    the composer
│   ├── AnswerView       routed answer: prose, entities, insights, sources
│   ├── GraphViewer      the D3 force-directed knowledge graph
│   ├── SourceManager    add/inspect ingestion sources
│   ├── CoordinatorDashboard   distributed worker-pool health
│   └── …                badges, banners, insight cards, empty states
└── types.ts             shared API types
```
