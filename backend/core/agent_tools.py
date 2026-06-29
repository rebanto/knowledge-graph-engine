"""
Agent-facing retrieval primitives.

These are the structured, relationship-aware lookups an external AI agent wants
when it uses this engine as its *grounded memory* instead of dumping raw
documents into its context window. They return compact, typed dicts (entities,
paths, conflicts) — not prose — so an agent can reason over them directly.

The MCP server (`backend/mcp/server.py`) wraps these one-to-one. They are kept
here, separate from the transport, so they are unit-testable and reusable by the
HTTP API too. Everything is workspace-scoped, matching the multi-tenant graph
keying (name, workspace_id).

Sharding: under USE_SHARDING the graph is split across N Neo4j instances and an
entity's edges live partly on its own shard and partly (as stubs) on the shards
that point at it. Every read here therefore fans out across all shards and merges
(via shard_router.run_read), exactly like graph_retriever — so an agent sees the
WHOLE graph, not just shard 0. When sharding is off, the single-node driver is
used directly (the default and fallback).
"""
from backend.db.neo4j import get_async_driver
from backend.db import shard_router


async def _read(cypher: str, params: dict, timeout: float = 12.0) -> list[dict]:
    """Run a read-only Cypher across all shards and merge (sharded), or against
    the single Neo4j instance (unsharded). Mirrors graph_retriever._exec."""
    if shard_router.is_enabled():
        return await shard_router.get_router().run_read(cypher, params, timeout)
    driver = await get_async_driver()
    async with driver.session() as session:
        result = await session.run(cypher, **params)
        return await result.data()


async def entity_context(workspace_id: str, name: str, limit: int = 25) -> dict:
    """The immediate neighbourhood of one entity: its type, degree, and the
    typed relationships radiating from it. The atomic 'what do you know about X'
    an agent asks before reasoning. Degree and neighbours are summed across shards
    so cross-shard edges are not missed."""
    rows = await _read(
        """
        MATCH (n {workspace_id: $ws})
        WHERE toLower(n.name) = toLower($name) AND coalesce(n.is_stub, false) = false
        OPTIONAL MATCH (n)-[r]-(m {workspace_id: $ws})
        RETURN n.name AS canonical, labels(n)[0] AS type,
               m.name AS neighbor, labels(m)[0] AS neighbor_type,
               type(r) AS relation, r.confidence AS confidence,
               coalesce(r.conflict_flag, false) AS conflict
        """,
        {"ws": workspace_id, "name": name},
    )
    if not rows:
        return {"found": False, "name": name, "neighbors": []}

    canonical = next((r["canonical"] for r in rows if r.get("canonical")), name)
    ntype = next((r["type"] for r in rows if r.get("type")), None)

    neighbors: list[dict] = []
    seen: set = set()
    for r in rows:
        if not r.get("neighbor"):
            continue
        key = (r["neighbor"], r["relation"])
        if key in seen:
            continue
        seen.add(key)
        neighbors.append({
            "neighbor": r["neighbor"],
            "neighbor_type": r["neighbor_type"],
            "relation": r["relation"],
            "confidence": r["confidence"],
            "conflict": r["conflict"],
        })

    return {
        "found": True,
        "name": canonical,
        "type": ntype,
        "degree": len(neighbors),
        "neighbors": neighbors[:limit],
    }


async def _neighbor_names(workspace_id: str, name: str) -> set[str]:
    rows = await _read(
        """
        MATCH (n {workspace_id: $ws})-[]-(m {workspace_id: $ws})
        WHERE toLower(n.name) = toLower($name)
        RETURN DISTINCT m.name AS neighbor
        """,
        {"ws": workspace_id, "name": name},
    )
    return {r["neighbor"] for r in rows if r.get("neighbor")}


async def find_path(
    workspace_id: str, source: str, target: str, max_hops: int = 5
) -> dict:
    """Shortest relationship path between two named entities — the multi-hop
    traversal vector search structurally cannot do. Returns the ordered nodes and
    the relationship types between them, or found=False if no path is found.

    Under sharding, a `shortestPath` runs on every shard (catching any same-shard
    path of any length); if none is found, a cross-shard two-hop fallback
    intersects the two endpoints' neighbour sets — the documented scatter-gather
    boundary for connections that straddle shards."""
    max_hops = max(1, min(int(max_hops), 8))  # keep the var-length scan bounded
    rows = await _read(
        f"""
        MATCH (a {{workspace_id: $ws}}), (b {{workspace_id: $ws}})
        WHERE toLower(a.name) = toLower($source) AND toLower(b.name) = toLower($target)
        MATCH p = shortestPath((a)-[*..{max_hops}]-(b))
        RETURN [n IN nodes(p) | {{name: n.name, type: labels(n)[0]}}] AS nodes,
               [r IN relationships(p) | type(r)] AS relations
        """,
        {"ws": workspace_id, "source": source, "target": target},
    )
    if rows:
        # Across shards there may be several candidates — take the shortest.
        best = min(rows, key=lambda r: len(r["relations"]))
        return _path_result(best["nodes"], best["relations"], source, target,
                            cross_shard=False)

    # Cross-shard two-hop fallback: a path a—m—b where the a→m and m→b edges live
    # on different shards is invisible to any single shortestPath. Intersect the
    # neighbour sets instead.
    if shard_router.is_enabled():
        na = await _neighbor_names(workspace_id, source)
        nb = await _neighbor_names(workspace_id, target)
        if target in na or source in nb:  # direct edge spanning shards
            return _path_result(
                [{"name": source, "type": None}, {"name": target, "type": None}],
                ["CONNECTED"], source, target, cross_shard=True)
        shared = sorted(na & nb)
        if shared:
            mid = shared[0]
            return _path_result(
                [{"name": source, "type": None}, {"name": mid, "type": None},
                 {"name": target, "type": None}],
                ["CONNECTED", "CONNECTED"], source, target,
                cross_shard=True, shared_neighbors=shared)

    return {"found": False, "source": source, "target": target, "path": []}


def _path_result(nodes, relations, source, target, *, cross_shard, shared_neighbors=None):
    hops = []
    for i, node in enumerate(nodes):
        hops.append({"node": node})
        if i < len(relations):
            hops.append({"relation": relations[i]})
    out = {
        "found": True,
        "source": nodes[0]["name"] if nodes else source,
        "target": nodes[-1]["name"] if nodes else target,
        "length": len(relations),
        "nodes": nodes,
        "relations": relations,
        "path": hops,
        "cross_shard": cross_shard,
    }
    if shared_neighbors is not None:
        out["shared_neighbors"] = shared_neighbors
    return out


