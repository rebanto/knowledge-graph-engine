# 01 — Overview

## What this is

A **research intelligence platform**. A user creates a *workspace*, points it at
*sources* (ArXiv categories/papers, RSS feeds, web URLs, uploaded PDFs), and
asks questions in natural language. The engine builds a knowledge graph of the
entities and relationships found in those sources and a vector index of the
document text, then answers questions by **querying real data structures** — not
by prompting an LLM to recall facts.

The system is **domain-agnostic**. The node labels (`Person`, `Organization`,
`Paper`, `Concept`, `Event`, `Topic`) are generic; a `Concept` can be a drug, a
legal principle, an algorithm, a financial instrument. The entity extractor
infers labels from context. The starting domain is **AI/ML research papers via
the ArXiv API**, because the data is free, well-structured, and easy to
evaluate.

## The core idea: a constrained LLM

This is deliberately **not an LLM wrapper**. The LLM is touched in exactly four
narrow places, all of which take structured input or produce structured output:

1. **Entity/relationship extraction** during ingestion
   ([`entity_extractor.py`](../backend/ingestion/entity_extractor.py)) — text in,
   JSON `{entities, relationships}` out.
2. **Query routing** ([`router.py`](../backend/core/router.py)) — question in,
   `{type: graph|vector|hybrid}` out.
3. **Cypher translation** ([`graph_retriever.py`](../backend/core/graph_retriever.py))
   — question + schema in, a single read-only Cypher query out (validated by a
   regex blocklist before execution).
4. **Answer synthesis** ([`synthesizer.py`](../backend/core/synthesizer.py)) —
   *retrieved* data in, prose + structured insight cards out, with a hard rule
   that every entity/number/date in the answer must appear in the retrieved
   data.

Everything else — graph storage and traversal, vector search, caching, conflict
detection, source attribution, sharding, the distributed worker pool — is
ordinary deterministic code.

There is also a **fifth, multimodal** LLM use that is easy to miss: OCR of
scanned PDFs ([`llm_client.ocr_pdf`](../backend/core/llm_client.py)), used only
when a PDF has no extractable text layer.

## Two retrieval systems, one router

| System | Store | Good for | Example question |
|--------|-------|----------|------------------|
| **Knowledge graph** | Neo4j (Cypher) | relationships between named entities | "How is researcher X connected to organization Y?" |
| **Vector search** | ChromaDB | knowledge / content retrieval | "What are the latest findings on topic X?" |

A lightweight Gemini classifier routes each question to `graph`, `vector`, or
`hybrid`. `hybrid` runs both retrievers in parallel and merges the results. When
in doubt the router is told to **prefer hybrid**. Full detail in
[Query pipeline](07-query-pipeline.md).

## Design principles (as embodied in the code)

- **Simple first, distributed second, with a working fallback at every step.**
  The single-Neo4j path and the single RQ worker are the default and remain
  fully functional. The distributed worker pool (Phase 3) and the shard router
  (Phase 4) are **opt-in via Docker Compose profiles and an env flag** — they
  layer on top without replacing the simpler path. You can always fall back.
- **Idempotency is non-negotiable.** Any document can be processed twice (worker
  reassignment, manual re-ingest, a late "dead" worker finishing its batch). All
  writes are replay-safe: Neo4j `MERGE`, ChromaDB `upsert` with deterministic
  IDs, conditional Postgres updates. See
  [Ingestion → Idempotency](06-ingestion-pipeline.md#idempotency).
- **Every fact is attributed.** Nodes and edges carry a `source_ids` list of the
  Postgres sources that asserted them, which is what makes precise source
  deletion possible. Vector chunks carry `source_id` and `source_url`.
- **No silent black holes.** A source that fetches zero documents, or whose
  every document fails, is marked `error` — never a green "success" that answers
  "no information." This was a real, observed failure class and the ingestion
  job goes out of its way to avoid it.
- **Reports are versioned.** Re-asking the same question in the same workspace
  creates a new `Report` row with an incremented `version`; old answers are
  preserved.
- **Local first.** No AWS services. Everything runs in Docker on one machine.

## Plan vs. reality

The root [`CLAUDE.md`](../CLAUDE.md) is the original project plan. The code has
moved ahead of it and diverges in a few important ways. **These docs describe
the code.** The notable differences:

| Topic | `CLAUDE.md` says | The code actually does |
|-------|------------------|------------------------|
| LLM provider | Anthropic Claude (`claude-sonnet-4-6`) | **Google Gemini** via `google-genai` (`gemini-flash-lite-latest` by default) — see [`llm_client.py`](../backend/core/llm_client.py) |
| Embeddings | OpenAI `text-embedding-3-small` *or* local | **Local `sentence-transformers` (`all-MiniLM-L6-v2`)** only — see [`chroma.py`](../backend/db/chroma.py) |
| Phase 3 (workers) | "not yet, but soon" | **Implemented and opt-in.** Coordinator + gRPC workers exist under the `distributed` Compose profile. The default remains the single RQ worker. |
| Phase 4 (sharding) | planned | **Implemented and opt-in** via `USE_SHARDING=true` and the `sharding` Compose profile. Default is single-node. |
| Phase 5 (API/UI) | "skeleton exists" | A substantial FastAPI backend and React SPA exist, including SSE streaming, graph visualization, and source management. |
| Edge types | a short list | a richer set including `MENTIONS`, `ABOUT`, `USES`, `PROPOSES`, `EXTENDS`, `EVALUATED_ON`, etc. — see [Data models](05-data-models.md#neo4j-graph-schema) |

The architectural *intent* of `CLAUDE.md` is intact — a constrained LLM, dual
retrieval, idempotent writes, a fallback-first rollout. Only the concrete
technology choices and the completion status differ.

## What is NOT built / out of scope

- **No AWS / cloud deployment.** Phase 7 is untouched by design.
- **No auth / multi-user isolation enforced.** The data model has
  `organizations`/`users` in the plan, but the running code does not implement
  authentication; workspaces are the only tenancy boundary in practice.
- **No LangChain / LlamaIndex.** The pipeline is built directly, on purpose.
- The coordinator is a **single process with no failover** — acceptable for
  local dev, called out in the plan as needing leader-election for production.

Continue to [Architecture](02-architecture.md).
