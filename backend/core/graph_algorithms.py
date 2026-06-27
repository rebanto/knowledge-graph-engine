"""
Graph algorithms over a workspace's knowledge graph.

CLAUDE.md lists "PageRank centrality" and "community detection" as capabilities;
this module is where they actually live. Both run with networkx over the
workspace subgraph rather than Neo4j GDS, deliberately:

  * No GDS plugin dependency — works against vanilla Neo4j (and, via the shard
    router's scatter-gather read, against the sharded layout unchanged).
  * The graphs here are hundreds–low-thousands of nodes, so an in-memory
    networkx pass is milliseconds and far simpler to reason about than a GDS
    projection lifecycle.

The compute functions (`compute_pagerank`, `compute_communities`) are pure: they
take an edge list and return ranked results, so they unit-test with no database.
The `workspace_*` coroutines wrap them with the edge loader + Redis cache.

PageRank is the honest replacement for the old "centrality = degree count":
degree counts immediate edges; PageRank propagates influence through the graph,
so an entity cited by influential entities outranks one with many trivial edges.
"""
import os
import networkx as nx

from backend.db import shard_router
from backend.db.neo4j import get_async_driver
from backend.db.redis import get_cached_graph_algo, set_cached_graph_algo

# Cap the subgraph pulled into memory so a pathologically large workspace can't
# stall the event loop. Well above the scale these graphs reach in practice.
_EDGE_LIMIT = int(os.environ.get("GRAPH_ALGO_EDGE_LIMIT", 20000))

# Stub nodes (cross-shard edge targets) carry no real identity, so they're
# excluded — they'd otherwise show up as phantom influential entities.
_EDGE_CYPHER = """
MATCH (a {workspace_id: $ws})-[r]->(b {workspace_id: $ws})
WHERE a.name IS NOT NULL AND b.name IS NOT NULL
  AND coalesce(a.is_stub, false) = false
  AND coalesce(b.is_stub, false) = false
RETURN a.name AS source, b.name AS target,
       labels(a)[0] AS source_type, labels(b)[0] AS target_type,
       coalesce(r.confidence, 1.0) AS confidence
LIMIT $limit
"""


# ── Pure compute (no I/O — unit-tested) ────────────────────────────────────────

def _node_types(edges: list[dict]) -> dict[str, str]:
    """Best-effort entity-name → label map harvested from the edge rows."""
    types: dict[str, str] = {}
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s and e.get("source_type") and s not in types:
            types[s] = e["source_type"]
        if t and e.get("target_type") and t not in types:
            types[t] = e["target_type"]
    return types


def build_digraph(edges: list[dict]) -> nx.DiGraph:
    """Directed, confidence-weighted multigraph collapsed to a DiGraph.

    Parallel edges between the same pair accumulate weight, so a relationship two
    sources both assert pulls more PageRank mass than a single low-confidence one.
    """
    g = nx.DiGraph()
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if not s or not t or s == t:
            continue
        w = float(e.get("confidence") or 1.0)
        if g.has_edge(s, t):
            g[s][t]["weight"] += w
        else:
            g.add_edge(s, t, weight=w)
    return g


def compute_pagerank(edges: list[dict], top_n: int = 25) -> list[dict]:
    """Rank entities by PageRank centrality over the directed graph.

    Returns [{"name", "type", "score"}] sorted by score desc. Empty when there
    are no usable edges.
    """
    g = build_digraph(edges)
    if g.number_of_nodes() == 0:
        return []
    scores = nx.pagerank(g, weight="weight")
    types = _node_types(edges)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [
        {"name": name, "type": types.get(name), "score": round(score, 6)}
        for name, score in ranked[:top_n]
    ]


def compute_communities(
    edges: list[dict], max_communities: int = 12, min_size: int = 2
) -> list[dict]:
    """Detect communities (densely connected entity clusters).

    Uses Louvain modularity maximization where available (networkx >= 3.0),
    falling back to greedy modularity. Runs on the undirected projection — a
    relationship connects two entities regardless of its direction. Returns
    [{"community_id", "size", "members", "top_member"}] sorted by size desc,
    where top_member is the highest-degree node (a readable label for the
    cluster). Singletons are dropped (min_size).
    """
    g = build_digraph(edges).to_undirected()
    if g.number_of_nodes() == 0:
        return []

    try:
        from networkx.algorithms.community import louvain_communities
        groups = louvain_communities(g, weight="weight", seed=42)
    except Exception:
        from networkx.algorithms.community import greedy_modularity_communities
        groups = greedy_modularity_communities(g, weight="weight")

    degree = dict(g.degree())
    communities = []
    for members in groups:
        members = list(members)
        if len(members) < min_size:
            continue
        members.sort(key=lambda n: degree.get(n, 0), reverse=True)
        communities.append({
            "size": len(members),
            "top_member": members[0],
            "members": members[:25],  # cap the payload; full size is reported above
        })

    communities.sort(key=lambda c: c["size"], reverse=True)
    for i, c in enumerate(communities[:max_communities]):
        c["community_id"] = i
    return communities[:max_communities]


# ── Workspace orchestration (edge loader + cache) ──────────────────────────────

async def _fetch_edges(workspace_id: str) -> list[dict]:
    """Load the workspace's edges for analysis.

    Routes through the shard router's scatter-gather read under USE_SHARDING so
    the algorithm sees the whole logical graph; otherwise the single-node driver.
    Mirrors graph_retriever._exec's backend selection.
    """
    params = {"ws": workspace_id, "limit": _EDGE_LIMIT}
    if shard_router.is_enabled():
        return await shard_router.get_router().run_read(_EDGE_CYPHER, params)
    driver = await get_async_driver()
    async with driver.session() as session:
        result = await session.run(_EDGE_CYPHER, **params)
        return await result.data()


async def workspace_influence(
    workspace_id: str, top_n: int = 25, use_cache: bool = True
) -> list[dict]:
    """Top entities by PageRank for a workspace (cached)."""
    if use_cache:
        cached = await get_cached_graph_algo(workspace_id, "influence")
        if cached is not None:
            return cached[:top_n]

    edges = await _fetch_edges(workspace_id)
    ranked = compute_pagerank(edges, top_n=max(top_n, 50))
    if use_cache:
        await set_cached_graph_algo(workspace_id, "influence", ranked)
    return ranked[:top_n]


async def workspace_communities(
    workspace_id: str, use_cache: bool = True
) -> list[dict]:
    """Entity communities for a workspace (cached)."""
    if use_cache:
        cached = await get_cached_graph_algo(workspace_id, "communities")
        if cached is not None:
            return cached

    edges = await _fetch_edges(workspace_id)
    communities = compute_communities(edges)
    if use_cache:
        await set_cached_graph_algo(workspace_id, "communities", communities)
    return communities


async def influence_for_names(
    workspace_id: str, names: list[str]
) -> list[dict]:
    """PageRank scores restricted to a set of entity names, in rank order.

    Used by the graph retriever to annotate the entities an answer touches with
    their global influence, reusing the cached whole-workspace ranking so the
    query path pays nothing beyond a dict lookup.
    """
    if not names:
        return []
    wanted = {n for n in names if n}
    ranked = await workspace_influence(workspace_id, top_n=10_000)
    return [r for r in ranked if r["name"] in wanted]
