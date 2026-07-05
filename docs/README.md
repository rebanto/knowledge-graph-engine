# Knowledge Graph Research Engine — Documentation

A research intelligence platform that answers complex questions by querying a
real knowledge graph of connected entities, not by asking an LLM to guess.

This `docs/` tree describes the system **as it is actually built** in this
repository. Where the implementation diverges from the high-level plan in the
root [`CLAUDE.md`](../CLAUDE.md), this documentation describes the code, and the
divergence is called out explicitly (see [Overview → Plan vs. reality](01-overview.md#plan-vs-reality)).

> **One thing to know up front:** the LLM is **Google Gemini** (via the
> `google-genai` SDK), not Anthropic Claude. `CLAUDE.md` names Claude as an
> aspiration; the running code uses Gemini everywhere. See
> [LLM integration](07-query-pipeline.md#the-llm-client).

---

## Table of contents

| #  | Document | What's in it |
|----|----------|--------------|
| 01 | [Overview](01-overview.md) | What the system is, its design philosophy, and where the code stands against the planned phases. |
| 02 | [Architecture](02-architecture.md) | The full component map, the two retrieval systems, request/data flow, process model. |
| 03 | [Getting started](03-getting-started.md) | Prerequisites, `.env`, the `dev.ps1` one-command startup, seeding, first query. |
| 04 | [Configuration](04-configuration.md) | Every environment variable, every Docker Compose profile, ports, resource limits. |
| 05 | [Data models](05-data-models.md) | PostgreSQL tables, the Neo4j graph schema, ChromaDB collections, Redis key layout. |
| 06 | [Ingestion pipeline](06-ingestion-pipeline.md) | Fetch → chunk → extract → write, idempotency, entity resolution, conflict detection, crash recovery. |
| 07 | [Query pipeline](07-query-pipeline.md) | Router → graph/vector retrieval → synthesizer, the LLM client, caching in the read path. |
| 08 | [API reference](08-api-reference.md) | Every REST endpoint, request/response shapes, the SSE streaming contract. |
| 09 | [Distributed worker pool](09-distributed-workers.md) | Phase 3: the gRPC coordinator/worker architecture, heartbeats, reassignment. |
| 10 | [Sharded knowledge graph](10-sharding.md) | Phase 4: the consistent-hash shard router, scatter-gather, stub nodes, benchmarks. |
| 11 | [Caching](11-caching.md) | The Redis cache layers, what is and isn't cached, invalidation, why answers are never cached. |
| 12 | [Resilience & observability](12-resilience-observability.md) | Circuit breakers, retries, bulkheads, Prometheus metrics, structured logging, health checks. |
| 13 | [Frontend](13-frontend.md) | The React + TypeScript SPA, components, the API client, the Vite proxy. |
| 14 | [Scripts](14-scripts.md) | Every script in `scripts/`: seeding, benchmarking, test harnesses. |
| 15 | [Operations & troubleshooting](15-operations.md) | Runbook, common failure modes, the "stuck source" story, manual recovery. |
| 16 | [Glossary](16-glossary.md) | Terms used throughout the codebase and these docs. |
| 17 | [Conversations](17-conversations.md) | Multi-turn follow-ups: query rewriting, the window + rolling-summary memory, threading. |
| 18 | [Evaluation](18-evaluation.md) | Measuring answer quality: routing accuracy, retrieval hit-rate, faithfulness (LLM-judge), entity-resolution P/R/F1, and the multi-hop graph-vs-vector benchmark. |
| 19 | [Deep research and MCP](19-deep-research-and-mcp.md) | Multi-agent research orchestration and the local MCP memory server. |
| 20 | [User auth](20-user-auth.md) | Self-hosted JWT auth, HttpOnly cookies, workspace ownership, and per-user history. |

---

## The 60-second mental model

```
            ┌──────────────── READ PATH (query) ────────────────┐
 question → │ Router (Gemini) → graph and/or vector retrieval →  │ → answer + insights
            │                    Synthesizer (Gemini)            │   (saved as a versioned Report)
            └────────────────────────────────────────────────────┘

            ┌──────────────── WRITE PATH (ingest) ──────────────┐
 source   → │ Fetch → Chunk → (embed → ChromaDB)                 │ → graph + vectors
            │                  (extract entities (Gemini) → Neo4j)│   (idempotent, replayable)
            └────────────────────────────────────────────────────┘
```

- **Graph** (Neo4j) answers *relationship* questions. **Vectors** (ChromaDB)
  answer *knowledge/content* questions. A **hybrid** question runs both.
- The LLM does exactly two narrow jobs: turn documents into structured
  entities/relationships, and turn structured retrieval results into prose. It
  does **not** invent facts.
- Users sign in through self-hosted FastAPI auth. Workspaces are private by
  owner, while `arxiv_seed` remains public read-only; reports and conversations
  are per-user inside that shared workspace.
- Everything between — storage, traversal, routing, caching, conflict
  detection, sharding — is ordinary code.

## Where the code lives

```
backend/    FastAPI app, ingestion pipeline, retrieval core, DB adapters, coordinator
frontend/   React + TypeScript SPA (Vite)
proto/      gRPC service definition for the distributed worker pool
scripts/    Seeding, benchmarking, and standalone test harnesses
docs/        You are here
```

A file-by-file map is in [Architecture → Repository layout](02-architecture.md#repository-layout).
