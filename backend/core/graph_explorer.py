from backend.db.neo4j import get_driver


def get_graph_data(workspace_id: str, limit: int = 150) -> dict:
    """
    Pick the highest-degree "hub" nodes, then return every edge actually
    incident to those hubs — including neighbors that aren't hubs themselves.
    Restricting edges to hub-to-hub pairs (the naive approach) tends to leave
    the most important nodes looking disconnected, since a hub's neighbors
    are often low-degree (e.g. a paper's one-off extracted concepts).
    """
    driver = get_driver()
    with driver.session() as session:
        hub_result = session.run(
            """
            MATCH (n {workspace_id: $workspace_id})
            OPTIONAL MATCH (n)-[r]-()
            WITH n, count(r) AS degree
            ORDER BY degree DESC
            LIMIT $hub_limit
            RETURN n.name AS name
            """,
            workspace_id=workspace_id,
            hub_limit=max(15, limit // 6),
        )
        hub_names = [record["name"] for record in hub_result]

        edge_result = session.run(
            """
            MATCH (hub {workspace_id: $workspace_id})-[r]-(neighbor {workspace_id: $workspace_id})
            WHERE hub.name IN $hub_names
            WITH DISTINCT r, startNode(r) AS s, endNode(r) AS t
            RETURN s.name AS source, labels(s)[0] AS source_type,
                   t.name AS target, labels(t)[0] AS target_type,
                   type(r) AS type, r.confidence AS confidence,
                   coalesce(r.conflict_flag, false) AS conflict
            LIMIT $edge_limit
            """,
            workspace_id=workspace_id,
            hub_names=hub_names,
            edge_limit=limit * 4,
        )

        edges = []
        node_info: dict[str, dict] = {}
        degree_count: dict[str, int] = {}

        for record in edge_result:
            edges.append({
                "source": record["source"],
                "target": record["target"],
                "type": record["type"],
                "confidence": record["confidence"],
                "conflict": record["conflict"],
            })
            for name, ntype in ((record["source"], record["source_type"]), (record["target"], record["target_type"])):
                node_info[name] = {"name": name, "type": ntype}
                degree_count[name] = degree_count.get(name, 0) + 1

        # Hubs with no surviving edges (isolated within the workspace) still get shown
        for name in hub_names:
            if name not in node_info:
                node_info[name] = {"name": name, "type": None}
                degree_count.setdefault(name, 0)

        nodes = [
            {**info, "degree": degree_count.get(name, 0)}
            for name, info in node_info.items()
            if info["type"] is not None
        ]

        # Cap total nodes shown, keeping the best-connected ones (within this
        # edge set) and dropping edges that no longer have both endpoints.
        if len(nodes) > limit:
            nodes.sort(key=lambda n: n["degree"], reverse=True)
            nodes = nodes[:limit]
            kept_names = {n["name"] for n in nodes}
            edges = [e for e in edges if e["source"] in kept_names and e["target"] in kept_names]

    return {"nodes": nodes, "edges": edges}
