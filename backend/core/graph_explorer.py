from backend.db import shard_router
from backend.db.neo4j import get_async_driver

_HUB_CYPHER = """
MATCH (n {workspace_id: $workspace_id})
OPTIONAL MATCH (n)-[r]-()
WITH n, count(r) AS degree
ORDER BY degree DESC
LIMIT $hub_limit
RETURN n.name AS name, degree
"""

_EDGE_CYPHER = """
MATCH (hub {workspace_id: $workspace_id})-[r]-(neighbor {workspace_id: $workspace_id})
WHERE hub.name IN $hub_names
WITH DISTINCT r, startNode(r) AS s, endNode(r) AS t
RETURN s.name AS source, labels(s)[0] AS source_type,
       t.name AS target, labels(t)[0] AS target_type,
       type(r) AS type, r.confidence AS confidence,
       coalesce(r.conflict_flag, false) AS conflict
LIMIT $edge_limit
"""


async def _read(cypher: str, params: dict) -> list[dict]:
    """Scatter-gather across shards under USE_SHARDING, else single-node.

    Mirrors graph_algorithms._fetch_edges — an entity's edges live on its
    owning shard, so the explorer must union all shards or the view silently
    drops every edge whose source entity hashes to another shard.
    """
    if shard_router.is_enabled():
        return await shard_router.get_router().run_read(cypher, params)
    driver = await get_async_driver()
    async with driver.session() as session:
        result = await session.run(cypher, **params)
        return await result.data()


async def get_graph_data(workspace_id: str, limit: int = 150) -> dict:
    """
    Pick the highest-degree hub nodes, then return every edge incident to those
    hubs — including low-degree neighbors. This avoids the naive hub-to-hub
    approach which leaves hub nodes looking disconnected from the periphery.
    """
    hub_limit = max(15, limit // 6)
    hub_rows = await _read(
        _HUB_CYPHER,
        {"workspace_id": workspace_id, "hub_limit": hub_limit},
    )

    # Under sharding a node's degree arrives split across shards (its own edges
    # plus stub-side references) — sum per name, then re-rank globally.
    hub_degree: dict[str, int] = {}
    for row in hub_rows:
        if row["name"] is not None:
            hub_degree[row["name"]] = hub_degree.get(row["name"], 0) + (row["degree"] or 0)
    hub_names = sorted(hub_degree, key=hub_degree.get, reverse=True)[:hub_limit]

    edge_rows = await _read(
        _EDGE_CYPHER,
        {
            "workspace_id": workspace_id,
            "hub_names": hub_names,
            "edge_limit": limit * 4,
        },
    )

    edges = []
    node_info: dict[str, dict] = {}
    degree_count: dict[str, int] = {}

    for record in edge_rows:
        edges.append({
            "source": record["source"],
            "target": record["target"],
            "type": record["type"],
            "confidence": record["confidence"],
            "conflict": record["conflict"],
        })
        for name, ntype in (
            (record["source"], record["source_type"]),
            (record["target"], record["target_type"]),
        ):
            node_info[name] = {"name": name, "type": ntype}
            degree_count[name] = degree_count.get(name, 0) + 1

    for name in hub_names:
        if name not in node_info:
            node_info[name] = {"name": name, "type": None}
            degree_count.setdefault(name, 0)

    nodes = [
        {**info, "degree": degree_count.get(name, 0)}
        for name, info in node_info.items()
        if info["type"] is not None
    ]

    if len(nodes) > limit:
        nodes.sort(key=lambda n: n["degree"], reverse=True)
        nodes = nodes[:limit]
        kept = {n["name"] for n in nodes}
        edges = [e for e in edges if e["source"] in kept and e["target"] in kept]

    return {"nodes": nodes, "edges": edges}
