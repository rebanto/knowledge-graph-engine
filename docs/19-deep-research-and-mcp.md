# Deep Research & the Agent Context Layer (MCP)

Two capabilities that turn the engine from "a grounded Q&A app" into something
no competitor (NotebookLM, Perplexity, Elicit, scite, GraphRAG, Glean) ships as
a package: a **multi-agent deep-research orchestrator** with a surfaced trust
score, and an **MCP server** that exposes the whole engine as *grounded memory
for any AI agent*.

Both are **opt-in and additive**. The single-shot `/question` pipeline is
unchanged and remains the always-working fallback (the project's "simple path
always survives" principle).

---

## 1. Multi-agent Deep Research

A single question runs one route and one synthesis. That caps out on compound
questions ("compare the funding networks behind A and B and what each cites").
Deep Research layers a lead-agent / sub-agent loop **on top of** the existing
pipeline:

```
question
   │
   ▼
 PLAN      lead LLM decomposes into 1–4 focused sub-questions, each routed
   │       (graph / vector / hybrid)
   ▼
 RESEARCH  each sub-question runs through the UNCHANGED qa pipeline
   │       (router → graph/vector → synthesizer), in bounded parallel.
   │       Each sub-agent is therefore independently grounded.
   ▼
 SYNTHESIZE lead LLM fuses the sub-answers — grounded ONLY in what the
   │        sub-agents retrieved (it introduces no new sources).
   ▼
 VERIFY    the faithfulness judge (backend/eval/judge.py) scores the fused
   │       report against the union of all retrieved evidence.
   ▼
 answer + sub-question trace + TRUST SCORE (supported-claim fraction)
```

The **trust score** is the differentiator on the answer itself: an independent
LLM judge checks every claim in the final report against the retrieved data and
reports the fraction supported, plus the specific claims it *couldn't* trace.
Most tools assert "grounded"; this one measures it and shows the number — and
the failures — to the user.

### Code

| File | Role |
|------|------|
| `backend/core/orchestrator.py` | `deep_research()` — the plan→research→synthesize→verify loop. Pure helpers (`_trust`, `_aggregate_evidence`, `_dedupe_entities`) are unit-tested. |
| `backend/api/routes/research.py` | `POST /api/research/deep` (run to completion) and `GET /api/research/deep/stream` (SSE: `status`/`plan`/`subagent`/`trust`/`done`). Persists a `Report` (`retrieval_type="deep_research"`). |
| `frontend/src/components/DeepResearchPanel.tsx` | Live trace: phase rail, sub-agent cards filling in as they finish, fused answer with the `TrustBadge` and flagged unsupported claims. |
| `frontend/src/components/TrustBadge.tsx` | The surfaced faithfulness pill. |

### Tuning (env)

```
DEEP_RESEARCH_CONCURRENCY=2        # parallel sub-agents (keeps the LLM burst small)
DEEP_RESEARCH_MAX_SUBQUESTIONS=4   # ceiling on decomposition
```

### Using it

In the UI, toggle **Deep Research** under the question box, then ask. Or:

```bash
curl -X POST localhost:8000/api/research/deep \
  -H 'content-type: application/json' \
  -d '{"question":"Compare the funding behind diffusion models and RLHF, and what each line of work cites","workspace_id":"arxiv_seed"}'
```

---

## 2. MCP server — the engine as agent memory

The "context problem": an agent stuffs raw documents into a finite context
window and hopes the right facts are present. Better: the agent *queries* a
grounded, relationship-aware store and gets back compact, traceable context.
`backend/mcp/server.py` exposes exactly that over the Model Context Protocol, so
any MCP client can call:

| Tool | What it returns |
|------|-----------------|
| `semantic_search(query, workspace_id, top_k)` | nearest document passages with sources |
| `graph_query(question, workspace_id)` | NL→Cypher over the graph: records + conflicts |
| `find_connection(entity_a, entity_b, workspace_id, max_hops)` | shortest relationship path — the multi-hop traversal vector search can't do |
| `get_entity_context(entity, workspace_id)` | an entity's typed neighbourhood |
| `check_conflicts(workspace_id, entity?)` | cross-source contradictions (CONFLICTS_WITH) |
| `deep_research(question, workspace_id)` | the full multi-agent loop + trust score |

The retrieval primitives live in `backend/core/agent_tools.py` (workspace-scoped,
unit-testable); the MCP layer is a thin transport over them and the existing
retrievers. It adds **no new way to fabricate facts** — same grounding guarantee
as the HTTP API.

### Run it

```bash
python -m backend.mcp.server      # stdio transport (the MCP default)
```

Requires the engine's databases (Neo4j, ChromaDB) reachable, same as the API.

### Register with an MCP client

**Easiest path — the in-app Connect page.** The web UI has a **Connect** tab
(`frontend/src/components/ConnectPanel.tsx`) that does this for the user: it calls
`GET /api/system/mcp-config?workspace_id=…` (`backend/api/routes/system.py`) and
renders a machine-specific, copy-paste config plus per-client, step-by-step
instructions (where the config file lives, what to paste, restart).

It supports the major MCP clients — **Claude Desktop, Claude Code, Cursor,
Windsurf, VS Code**, and a generic "any other client" fallback — and emits each in
that client's *correct* schema: the `mcpServers` object for Claude Desktop / Claude
Code / Cursor / Windsurf, and VS Code's top-level `servers` map with
`"type": "stdio"`. Every file path is derived at request time from the current
user's home / app-data dirs (`Path.home()`, `%APPDATA%`, `$XDG_CONFIG_HOME`) and
the running interpreter's `sys.executable`, so it's correct for **any user on any
OS** — nothing is hard-coded to one machine. `command`/`args` stay as separate
array elements so paths with spaces (`C:\Users\John Doe\…`) need no quoting.

The generated block is **self-contained** — it pins the API's own Python
interpreter, sets `PYTHONPATH`/`cwd` to the project root, selects the current
workspace via `MCP_DEFAULT_WORKSPACE`, and copies the database/LLM env the API is
already using — so a non-technical user copies one block, restarts their AI tool,
and it works. The page also warns if the `mcp` package is missing, if the databases
look Docker-internal (hostnames need to be `localhost`), or if `GEMINI_API_KEY` is
unset.

**Manual equivalent.** Point any MCP client's server config at the command
(adjust the path and env to your setup):

```json
{
  "mcpServers": {
    "knowledge-graph-engine": {
      "command": "python",
      "args": ["-m", "backend.mcp.server"],
      "env": {
        "MCP_DEFAULT_WORKSPACE": "arxiv_seed"
      }
    }
  }
}
```

Either way, an external agent can then ask *its own* questions against your
private, relationship-aware corpus — and get back paths, neighbourhoods,
conflicts, and faithfulness-scored research instead of a wall of chunks.

---

## Why this is the moat

| Capability | This engine | NotebookLM | Perplexity | Elicit | scite | GraphRAG | Glean |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| Multi-hop relationship traversal | ✅ | ❌ | ❌ | ❌ | ❌ | ⚠️ | ⚠️ |
| Cross-source conflict detection | ✅ | ❌ | ❌ | ❌ | ⚠️ | ❌ | ❌ |
| Measured + surfaced faithfulness score | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Multi-agent deep research | ✅ | ❌ | ⚠️ | ❌ | ❌ | ❌ | ⚠️ |
| Exposed as agent memory over MCP | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

The last two rows are the headline: a private, grounded, relationship-aware
**context layer for the agent ecosystem**, with research that fact-checks itself.
