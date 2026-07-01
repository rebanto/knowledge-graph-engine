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
import itertools
import json
import networkx as nx

from backend.core.llm_client import generate_json
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
       type(r) AS relation_type,
       coalesce(r.confidence, 1.0) AS confidence
LIMIT $limit
"""

EDGE_VOCABULARY = [
    "AUTHORED",
    "CITED",
    "FUNDED_BY",
    "CONFLICTS_WITH",
    "COLLABORATED_WITH",
    "PUBLISHED_IN",
    "SUPPORTS",
    "CONTRADICTS",
]


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


def _community_lookup(edges: list[dict]) -> dict[str, int]:
    """Map every node name to community id using the same algorithm as the UI."""
    graph = build_digraph(edges).to_undirected()
    if graph.number_of_nodes() == 0:
        return {}

    try:
        from networkx.algorithms.community import louvain_communities
        groups = louvain_communities(graph, weight="weight", seed=42)
    except Exception:
        from networkx.algorithms.community import greedy_modularity_communities
        groups = greedy_modularity_communities(graph, weight="weight")

    groups = sorted((list(g) for g in groups), key=len, reverse=True)
    lookup: dict[str, int] = {}
    for cid, members in enumerate(groups):
        for member in members:
            lookup[member] = cid
    return lookup


def _relation_between(edges: list[dict], a: str, b: str) -> list[str]:
    """Relationship types present on either direction of an evidence leg."""
    rels: set[str] = set()
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if {s, t} == {a, b}:
            rel = e.get("relation_type") or e.get("type")
            if rel:
                rels.add(str(rel))
    return sorted(rels)


def _entity(name: str, types: dict[str, str | None]) -> dict:
    return {"name": name, "type": types.get(name)}


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


def compute_research_gaps(edges: list[dict], top_n: int = 10) -> list[dict]:
    """Rank plausible missing links using networkx link-prediction metrics.

    Candidate pairs are non-adjacent nodes with at least one shared
    intermediary. The score combines Adamic-Adar, resource allocation,
    common-neighbor count, and a PageRank endpoint boost.
    """
    digraph = build_digraph(edges)
    graph = digraph.to_undirected()
    if graph.number_of_nodes() == 0:
        return []

    types = _node_types(edges)
    pagerank = nx.pagerank(digraph, weight="weight") if digraph.number_of_nodes() else {}
    max_pr = max(pagerank.values(), default=0.0) or 1.0
    communities = _community_lookup(edges)

    candidates: set[tuple[str, str]] = set()
    for intermediary in graph.nodes:
        neighbors = sorted(graph.neighbors(intermediary))
        for a, c in itertools.combinations(neighbors, 2):
            if a == c or graph.has_edge(a, c):
                continue
            candidates.add(tuple(sorted((a, c))))

    if not candidates:
        return []

    aa = {
        tuple(sorted((u, v))): score
        for u, v, score in nx.adamic_adar_index(graph, candidates)
    }
    ra = {
        tuple(sorted((u, v))): score
        for u, v, score in nx.resource_allocation_index(graph, candidates)
    }

    gaps = []
    for a, c in candidates:
        common = sorted(nx.common_neighbors(graph, a, c))
        if not common:
            continue

        pr_boost = 1.0 + (pagerank.get(a, 0.0) / max_pr) + (pagerank.get(c, 0.0) / max_pr)
        base_score = aa.get((a, c), 0.0) + ra.get((a, c), 0.0) + (0.25 * len(common))
        community_a = communities.get(a)
        community_c = communities.get(c)
        same_community = (
            community_a is not None and community_c is not None and community_a == community_c
        )
        interdisciplinary = (
            community_a is not None
            and community_c is not None
            and community_a != community_c
            and len(common) >= 2
        )
        if interdisciplinary:
            base_score *= 1.15

        evidence = [
            {
                "intermediary": _entity(b, types),
                "source_relation_types": _relation_between(edges, a, b),
                "target_relation_types": _relation_between(edges, b, c),
            }
            for b in common
        ]

        gaps.append({
            "source": _entity(a, types),
            "target": _entity(c, types),
            "shared_intermediaries": evidence,
            "score": round(base_score * pr_boost, 6),
            "common_neighbor_count": len(common),
            "same_community": same_community,
            "interdisciplinary": interdisciplinary,
            "community_ids": {"source": community_a, "target": community_c},
            "why_notable": (
                f"{len(common)} shared intermediaries with no direct graph edge"
                + (" across detected communities." if interdisciplinary else ".")
            ),
        })

    gaps.sort(
        key=lambda g: (
            g["score"],
            g["common_neighbor_count"],
            g["source"]["name"],
            g["target"]["name"],
        ),
        reverse=True,
    )
    return gaps[:top_n]


def find_research_gap(edges: list[dict], source: str, target: str) -> dict | None:
    """Return structural gap evidence for one unordered pair, if it is a gap."""
    wanted = {source.strip().lower(), target.strip().lower()}
    if len(wanted) != 2:
        return None

    for gap in compute_research_gaps(edges, top_n=10_000):
        names = {gap["source"]["name"].lower(), gap["target"]["name"].lower()}
        if names == wanted:
            return gap
    return None


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


async def workspace_research_gaps(
    workspace_id: str, limit: int = 10, use_cache: bool = True
) -> list[dict]:
    """Top read-only research gaps for a workspace (cached)."""
    if use_cache:
        cached = await get_cached_graph_algo(workspace_id, "gaps")
        if cached is not None:
            return cached[:limit]

    edges = await _fetch_edges(workspace_id)
    gaps = compute_research_gaps(edges, top_n=max(limit, 50))
    if use_cache:
        await set_cached_graph_algo(workspace_id, "gaps", gaps)
    return gaps[:limit]


async def workspace_gap_hypothesis(
    workspace_id: str, source: str, target: str
) -> dict | None:
    """Phrase one testable conjecture for a selected structural gap."""
    edges = await _fetch_edges(workspace_id)
    gap = find_research_gap(edges, source, target)
    if gap is None:
        return None
    phrasing = await phrase_hypothesis(gap)
    return {
        **phrasing,
        "source": gap["source"],
        "target": gap["target"],
        "evidence": gap["shared_intermediaries"],
        "common_neighbor_count": gap["common_neighbor_count"],
        "same_community": gap["same_community"],
        "interdisciplinary": gap["interdisciplinary"],
    }


async def phrase_hypothesis(gap: dict) -> dict:
    """Use the LLM only to phrase a conjecture from structural evidence."""
    evidence = {
        "source": gap["source"],
        "target": gap["target"],
        "common_neighbor_count": gap["common_neighbor_count"],
        "same_community": gap["same_community"],
        "interdisciplinary": gap["interdisciplinary"],
        "shared_intermediaries": gap["shared_intermediaries"][:12],
        "unproven_missing_edge": True,
    }
    prompt = f"""
You are phrasing a read-only knowledge-graph conjecture.

Return ONLY valid JSON with these fields:
{{
  "statement": "one testable hypothesis, explicitly labelled as a conjecture",
  "predicted_relationship_type": one of {EDGE_VOCABULARY},
  "confidence": "low" | "medium" | "high",
  "reasoning": "one sentence grounded only in the structural evidence",
  "caveat": "one sentence saying the predicted A-C edge is unproven"
}}

Hard rules:
- This is a PREDICTION/CONJECTURE, not an established fact.
- Ground the reasoning ONLY in the structural evidence below.
- Do not assert any outside-world fact or source claim.
- The predicted A-C edge is explicitly unproven and must not be described as known.

Structural evidence:
{json.dumps(evidence, default=str)}
"""
    result = await generate_json(prompt)
    rel = result.get("predicted_relationship_type")
    if rel not in EDGE_VOCABULARY:
        rel = "SUPPORTS"
    confidence = str(result.get("confidence") or "medium").lower()
    if confidence not in {"low", "medium", "high"}:
        confidence = "medium"
    return {
        "statement": result.get("statement")
        or (
            f"CONJECTURE: {gap['source']['name']} may have an untested "
            f"{rel} relationship with {gap['target']['name']}."
        ),
        "predicted_relationship_type": rel,
        "reasoning": result.get("reasoning") or gap.get("why_notable", ""),
        "confidence": confidence,
        "caveat": result.get("caveat")
        or "This is a structural conjecture only; the direct relationship is not present in the graph.",
    }


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
