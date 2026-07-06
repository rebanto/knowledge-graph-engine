---
title: Knowledge Graph Research Engine
sdk: docker
app_port: 7860
---

# Knowledge Graph Research Engine

A research intelligence platform that answers complex questions by querying a
**real knowledge graph** of connected entities — not by asking an LLM to guess.

Point a workspace at sources (arXiv categories, RSS feeds, web pages, PDFs) and
ask questions in natural language. A router decides whether each question is
answered by **graph traversal** (relationship questions), **vector search**
(knowledge questions), or both. The LLM only translates questions into queries
and results into prose — **it never generates facts**, and every claim in every
answer is checked against the retrieved evidence and scored.

> **This is not an LLM wrapper.** Graph storage, traversal, consistent-hash
> sharding, distributed ingestion, conflict detection, caching, and evaluation
> are all real code you can read in this repo.

## What it does

- **Dual retrieval with routing** — Neo4j graph traversal for "how is X
  connected to Y?", ChromaDB vector search for "what's the state of Z?", hybrid
  for both. An LLM classifier picks the route; empty results fall back to the
  other retriever.
- **Trust scores on every answer** — an independent LLM judge traces each claim
  in the answer back to the retrieved graph rows / passages. The UI shows the
  supported-claim fraction and lists any claim it couldn't verify.
- **Multi-agent Deep Research** — a lead agent decomposes a question into
  routed sub-questions, sub-agents research them in bounded parallel, and the
  fused report is fact-checked before you see it.
- **Conflict detection** — when two sources make contradictory claims about the
  same relationship, a `CONFLICTS_WITH` edge is auto-created and surfaced in
  answers and the graph view.
- **Conversations** — follow-ups are rewritten into standalone questions with
  bounded thread memory, then run through the same grounded pipeline.
- **Research-gap discovery** — link-prediction over the graph surfaces entity
  pairs that *should* be connected but aren't, with ranked strength tiers,
  shared-intermediary evidence, graph preview highlighting, and generated
  hypotheses.
- **MCP server** — the whole engine doubles as grounded memory for any AI agent
  via the Model Context Protocol: `semantic_search`, `graph_query`,
  `find_connection`, `get_entity_context`, `check_conflicts`, `deep_research`.
- **Distributed by design (and measured)** — an optional gRPC coordinator/worker
  pool with heartbeat-based failure recovery replaces the single ingestion
  worker, and an optional consistent-hash shard router splits the graph across
  three Neo4j instances. Both are opt-in, benchmarked
  ([sharding results](docs/10-sharding.md)), and layered over an always-working
  single-node path.
- **Evaluated, not asserted** — a checked-in golden set scores routing accuracy,
  retrieval hit-rate, faithfulness (unsupported-claim rate), and entity-resolution
  F1 ([methodology](docs/18-evaluation.md)). A multi-hop benchmark shows
  concretely what graph traversal does that vector search structurally can't.

## Architecture

```
User question
      |
 Query Router  (LLM classifies: graph | vector | hybrid)
      |
   ┌──┴────────────────────────┐
   |                           |
Graph retrieval            Vector search
(Neo4j; Cypher generated,  (ChromaDB; bi-encoder retrieve,
 validated, self-repaired;  cross-encoder rerank)
 optional 3-shard router)
   |                           |
   └──────────┬────────────────┘
              |
      Result Synthesizer  (LLM prose, citations only from retrieved data)
              |
      Faithfulness judge  (every claim traced → trust score)
              |
      Report (saved, versioned, conversational)
```

Ingestion runs the same per-document pipeline (fetch → chunk → embed → LLM
entity/relationship extraction → entity resolution → idempotent MERGE/upsert)
under either a simple RQ worker or the distributed coordinator/worker pool.
Full diagrams and design rationale: [docs/02-architecture.md](docs/02-architecture.md).

## Quickstart

Prerequisites: Docker Desktop, Python 3.11+, Node 18+, and a
[Gemini API key](https://aistudio.google.com/apikey) (free tier works).

```powershell
Copy-Item .env.example .env   # then set GEMINI_API_KEY=...
.\dev.ps1                     # starts infra + backend + worker + frontend
```

Then open http://localhost:5173, create a workspace (or use the seeded arXiv
one), add a source, and ask a question. Not on Windows? The manual startup
steps are in [docs/03-getting-started.md](docs/03-getting-started.md).

Optional profiles:

```bash
docker compose --profile distributed up -d   # gRPC coordinator + 3 workers
docker compose --profile sharding up -d      # 3 Neo4j shards (+ USE_SHARDING=true)
```

## Tech stack

| Layer | Technology |
|-------|------------|
| Graph database | Neo4j (single node, or 3 shards behind a consistent-hash router) |
| Vector store | ChromaDB (shared server) + local `sentence-transformers` embeddings |
| Relational / cache / queue | PostgreSQL · Redis · RQ |
| Distributed ingestion | Custom gRPC coordinator + Docker worker pool |
| LLM | Google Gemini (extraction, routing, synthesis, judging, OCR) |
| API / UI | FastAPI · React + TypeScript + D3 |

No LangChain / LlamaIndex — the pipeline is built directly so the architecture
stays transparent.

## Documentation

The [docs/](docs/README.md) directory covers everything: architecture, data
models, ingestion and query pipelines, distributed workers, sharding (with
benchmark results), caching, resilience, evaluation methodology, conversations,
Deep Research, and the MCP server.

## Testing

```bash
pip install -r requirements-dev.txt
pytest                     # unit + integration (Neo4j tests auto-skip if it's down)
python scripts/benchmark_quality.py    # routing / retrieval / faithfulness eval
python scripts/benchmark_sharding.py   # single-node vs sharded latency
```
