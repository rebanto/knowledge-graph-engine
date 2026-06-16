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

```
User question
      |
 Query Router
 (LLM classifies question type)
      |
   ┌──┴────────────────┐
   |                   |
Graph Traversal    Vector Search
(relationship Q's) (knowledge Q's)
   |                   |
   └──────┬────────────┘
          |
    Result Synthesizer
    (LLM turns structured results into prose)
          |
      Report (saved, versioned, shareable)
```

### Ingestion Pipeline (shared by both retrieval systems)

```
Source (RSS / ArXiv API / uploaded PDF)
      |
 Fetch Worker
      |
 Entity Extractor (LLM — constrained JSON output only)
      |
   ┌──┴─────────────────┐
   |                    |
Neo4j Graph DB     Vector Store
(entities + edges) (embedded chunks)
```

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
- **Queries written in:** Gremlin (Apache TinkerPop)
- **Algorithms used:** shortest path, PageRank centrality, community detection,
  contradiction detection (when two sources make conflicting claims about an edge)

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

## Tech Stack

### Local Development (current phase — use these)

| Component            | Local Tool         | Notes                                      |
|----------------------|--------------------|--------------------------------------------|
| Graph database       | Neo4j (Docker)     | Free, same Gremlin queries as AWS Neptune  |
| Vector store         | ChromaDB           | Lightweight, runs in-process, no server    |
| Relational database  | PostgreSQL (Docker)| User accounts, reports, workspaces         |
| Cache                | Redis (Docker)     | Cache expensive graph traversals           |
| Message queue        | Redis Queue (RQ)   | Simple job queue using Redis               |
| LLM API              | Anthropic Claude API (claude-sonnet-4-6) | Entity extraction, routing, synthesis |
| Embedding model      | OpenAI text-embedding-3-small OR local sentence-transformers | |
| Document ingestion   | Python scripts     | ArXiv API to start                         |
| Backend API          | FastAPI (Python)   | REST API                                   |
| Frontend             | React + TypeScript | Simple UI — query input + report viewer    |
| Background workers   | Python RQ workers  | Process ingestion jobs from queue          |

### Cloud Deployment (future phase — do not build yet)

| Local Tool    | AWS Equivalent         |
|---------------|------------------------|
| Neo4j         | Amazon Neptune         |
| ChromaDB      | Amazon OpenSearch      |
| PostgreSQL    | Amazon RDS             |
| Redis         | Amazon ElastiCache     |
| Redis Queue   | Amazon SQS             |
| RQ Workers    | AWS Lambda / ECS       |
| FastAPI app   | Amazon ECS / Fargate   |
| File storage  | Amazon S3              |
| Auth          | Amazon Cognito         |
| Orchestration | AWS Step Functions     |

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
```

### ChromaDB Collections (vector data)

```
Collection per workspace: "workspace_{workspace_id}_chunks"

Each chunk document:
  - text: the chunk content
  - metadata:
      source_url, source_title, source_date,
      chunk_index, workspace_id,
      entity_mentions: [list of entity names found in chunk]
```

---

## Ingestion Pipeline (detailed)

This is the core background process. One document flows through these steps:

```
1. Fetch document (HTTP request or PDF parse)
2. Clean and chunk text (~512 token chunks with 50 token overlap)
3. Parallel:
   a. Embed chunks → store in ChromaDB
   b. LLM entity extraction:
        Prompt: "Extract all named entities and relationships from this text.
                 Return ONLY valid JSON: {entities: [...], relationships: [...]}
                 Entity fields: name, type, aliases[]
                 Relationship fields: source, target, type, context, confidence"
        → Parse JSON response
        → Entity resolution: merge with existing nodes (fuzzy name match)
        → Write nodes and edges to Neo4j
4. Mark ingestion_job as complete in PostgreSQL
```

**Entity resolution rule:** If a new entity name has >0.85 cosine similarity
to an existing entity name (same type), treat as the same entity and merge
properties. Do not create duplicate nodes.

---

## Query Flow (detailed)

When a user submits a question:

```
1. Router LLM call:
   Prompt: "Classify this research question. Return JSON only:
            {type: 'graph'|'vector'|'hybrid', reasoning: '...'}"

2a. If graph:
    - LLM translates question to Gremlin traversal
    - Execute against Neo4j
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
├── docker-compose.yml         ← Neo4j, PostgreSQL, Redis
├── .env                       ← API keys and config (never commit)
├── .env.example               ← Template for .env
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
│   │   ├── graph_retriever.py ← Neo4j query logic
│   │   ├── vector_retriever.py← ChromaDB query logic
│   │   └── synthesizer.py     ← LLM answer generation
│   ├── ingestion/
│   │   ├── fetcher.py         ← Fetch documents from sources
│   │   ├── chunker.py         ← Split documents into chunks
│   │   ├── entity_extractor.py← LLM entity/relationship extraction
│   │   ├── entity_resolver.py ← Merge duplicate entities
│   │   └── worker.py          ← RQ worker that runs the pipeline
│   ├── db/
│   │   ├── postgres.py        ← SQLAlchemy models and session
│   │   ├── neo4j.py           ← Neo4j driver and query helpers
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
│   │   │   └── GraphViewer.tsx  ← D3.js graph visualization
│   │   └── App.tsx
│
└── scripts/
    └── seed_arxiv.py          ← One-time script to seed graph from ArXiv
```

---

## Build Phases

**Current phase: Phase 1**

### Phase 1 — Local pipeline (no UI)
- [ ] docker-compose.yml with Neo4j, PostgreSQL, Redis
- [ ] ArXiv fetcher script
- [ ] Entity extractor (LLM → JSON → Neo4j)
- [ ] ChromaDB embedding pipeline
- [ ] Seed graph with 500 AI/ML papers
- [ ] Verify graph has real nodes and edges

### Phase 2 — Query layer (no UI)
- [ ] Query router (classify question type)
- [ ] Graph retriever (Gremlin queries for relationship questions)
- [ ] Vector retriever (ChromaDB similarity search)
- [ ] Synthesizer (LLM answer from structured results)
- [ ] Test with 10 real questions, evaluate answer quality

### Phase 3 — API + basic UI
- [ ] FastAPI app with /question and /reports endpoints
- [ ] Simple React frontend (question input + answer display)
- [ ] PostgreSQL for saving reports
- [ ] Redis caching for repeated graph queries

### Phase 4 — Polish
- [ ] Graph visualization (D3.js) showing entity relationships
- [ ] Conflict detection and flagging in answers
- [ ] Source provenance (every fact links to its source document)
- [ ] Multi-workspace support

### Phase 5 — AWS deployment (future)
- [ ] Migrate Neo4j → Neptune
- [ ] Migrate ChromaDB → OpenSearch
- [ ] Migrate PostgreSQL → RDS
- [ ] Migrate Redis Queue → SQS + Lambda
- [ ] Deploy API → ECS/Fargate
- [ ] Add Cognito auth

---

## Environment Variables (.env)

```
ANTHROPIC_API_KEY=
OPENAI_API_KEY=           # for embeddings (or use sentence-transformers)

NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=

POSTGRES_URL=postgresql://user:password@localhost:5432/kgre
REDIS_URL=redis://localhost:6379

CHROMA_PERSIST_DIR=./chroma_data
```

---

## Key Decisions Already Made

- **Local first, AWS later.** Do not introduce cloud services until Phase 5.
- **Neo4j over Neptune locally.** Same Gremlin query language, free, Docker.
- **ChromaDB over OpenSearch locally.** Simpler, runs in-process, no server.
- **ArXiv as the starting domain.** Free API, well-structured data.
- **LLM is constrained.** It only extracts entities (JSON output) and
  synthesizes answers (from retrieved results). It never generates facts freely.
- **Dual retrieval with routing.** Graph for relationships, vector for knowledge,
  hybrid for mixed questions. Router is an LLM classifier.
- **Entity resolution is required.** Duplicate nodes break the graph.
  Fuzzy match on name + type before creating new nodes.
- **Reports are versioned.** Re-running the same question creates a new version,
  old ones are preserved.

---

## What NOT to Do

- Do not use LangChain or LlamaIndex. Build the pipeline directly so the
  architecture is transparent and learnable.
- Do not skip entity resolution. Duplicate nodes make the graph useless.
- Do not let the LLM generate unsourced facts in answers. Every claim must
  trace to a retrieved document or graph result.
- Do not build Phase 2 before Phase 1 is verified working.
- Do not introduce AWS services before Phase 5.
