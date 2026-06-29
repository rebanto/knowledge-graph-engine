"""
Knowledge-Graph-Engine MCP server — the engine as *grounded memory for agents*.

The differentiator: an AI agent shouldn't paste raw documents into its context
window and hope the right facts are in there. It should QUERY a grounded,
relationship-aware store and get back structured, traceable context. This server
exposes exactly that over the Model Context Protocol, so any MCP client
(Claude Desktop, Cursor, an Agent-SDK agent, …) can call:

    semantic_search     – nearest document passages (with sources)
    graph_query         – natural-language → Cypher over the knowledge graph
    find_connection     – shortest relationship path A↔B (the multi-hop traversal
                          vector search can't do)
    get_entity_context  – an entity's typed neighbourhood
    check_conflicts     – cross-source contradictions (CONFLICTS_WITH edges)
    deep_research       – the full multi-agent plan→research→verify loop, returned
                          with a faithfulness/trust score

Every tool is workspace-scoped and returns only retrieved/derived data — the
same grounding guarantee the HTTP API gives. This is a thin transport over the
real retrievers in backend/core; it adds no new way to fabricate facts.

Run (stdio transport, the MCP default):

    python -m backend.mcp.server

Register it with an MCP client by pointing the client's server config at that
command. Requires the engine's databases (Neo4j, ChromaDB) to be reachable, same
as the API.
"""
import os

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - clearer message than a raw ImportError
    raise SystemExit(
        "The 'mcp' package is required to run the MCP server. "
        "Install it with: pip install mcp"
    ) from exc

from backend.core.vector_retriever import run_vector_query
from backend.core.graph_retriever import run_graph_query
from backend.core import agent_tools
from backend.core.orchestrator import deep_research as _deep_research

# Default workspace so simple clients can omit it; override per call.
DEFAULT_WORKSPACE = os.environ.get("MCP_DEFAULT_WORKSPACE", "arxiv_seed")

mcp = FastMCP("knowledge-graph-engine")


@mcp.tool()
async def semantic_search(query: str, workspace_id: str = DEFAULT_WORKSPACE,
                          top_k: int = 5) -> dict:
    """Find the document passages most semantically similar to `query`.

    Use for content/knowledge needs ("what does the corpus say about X"). Returns
    passages with their source title/url so the agent can cite them.
    """
    result = await run_vector_query(query, workspace_id, top_k=top_k)
    return {"chunks": result.get("chunks", [])}


@mcp.tool()
async def graph_query(question: str, workspace_id: str = DEFAULT_WORKSPACE) -> dict:
    """Answer a relationship question by generating and running Cypher over the
    knowledge graph. Use for "who/what connects/authored/cites/funds" questions.
    Returns the generated Cypher, the matched records, and any conflict flags.
    """
    result = await run_graph_query(question, workspace_id)
    return {
        "cypher": result.get("cypher"),
        "records": result.get("records", []),
        "conflicts": result.get("conflicts", []),
    }


@mcp.tool()
async def find_connection(entity_a: str, entity_b: str,
                          workspace_id: str = DEFAULT_WORKSPACE,
                          max_hops: int = 5) -> dict:
    """Find the shortest relationship path between two named entities — the
    multi-hop traversal a vector store cannot do. Returns the ordered nodes and
    the relationship types linking them, or found=False if none within max_hops.
    """
    return await agent_tools.find_path(workspace_id, entity_a, entity_b, max_hops)


@mcp.tool()
async def get_entity_context(entity: str, workspace_id: str = DEFAULT_WORKSPACE,
                             limit: int = 25) -> dict:
    """Get the immediate neighbourhood of one entity: its type, degree, and the
    typed relationships around it. The grounded 'what do you know about X' an
    agent asks before reasoning.
    """
    return await agent_tools.entity_context(workspace_id, entity, limit)


@mcp.tool()
async def check_conflicts(workspace_id: str = DEFAULT_WORKSPACE,
                          entity: str | None = None) -> dict:
    """List entity pairs the sources disagree about (CONFLICTS_WITH edges),
    optionally filtered to one entity. Lets an agent weigh contradictory evidence
    instead of silently picking one source.
    """
    conflicts = await agent_tools.list_conflicts(workspace_id, entity)
    return {"conflicts": conflicts}


@mcp.tool()
async def deep_research(question: str,
                        workspace_id: str = DEFAULT_WORKSPACE) -> dict:
    """Run the full multi-agent deep-research loop: decompose the question into
    sub-questions, research each over graph + vector, fuse the findings, and
    fact-check the result. Returns the report, the sub-question trace, and a
    faithfulness `trust` score. Use for compound/complex questions.
    """
    result = await _deep_research(question, workspace_id)
    return {
        "answer": result["answer"],
        "subquestions": result["subquestions"],
        "trust": result["trust"],
        "conflicts": result["conflicts"],
        "key_entities": result["key_entities"],
    }


if __name__ == "__main__":
    mcp.run()
