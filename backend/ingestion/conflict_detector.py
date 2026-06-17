from backend.db.neo4j import get_driver

OPPOSITE = {"SUPPORTS": "CONTRADICTS", "CONTRADICTS": "SUPPORTS"}


def check_and_flag_conflict(
    source_name: str,
    target_name: str,
    edge_type: str,
    source_document_id: str,
    workspace_id: str,
) -> bool:
    """
    After creating a SUPPORTS/CONTRADICTS edge, check whether an opposing edge
    already exists between the same node pair from a *different* source
    document. If so, flag both edges as conflicting and create a
    CONFLICTS_WITH edge between the two nodes.
    """
    opposite = OPPOSITE.get(edge_type)
    if not opposite:
        return False

    with get_driver().session() as session:
        result = session.run(
            f"""
            MATCH (a {{name: $source_name, workspace_id: $workspace_id}})
                  -[r:{opposite}]->
                  (b {{name: $target_name, workspace_id: $workspace_id}})
            WHERE r.source_document_id <> $source_document_id
            RETURN count(r) AS count
            """,
            source_name=source_name,
            target_name=target_name,
            workspace_id=workspace_id,
            source_document_id=source_document_id,
        )
        has_conflict = result.single()["count"] > 0

        if has_conflict:
            session.run(
                """
                MATCH (a {name: $source_name, workspace_id: $workspace_id})
                      -[r]->
                      (b {name: $target_name, workspace_id: $workspace_id})
                WHERE type(r) IN ['SUPPORTS', 'CONTRADICTS']
                SET r.conflict_flag = true
                """,
                source_name=source_name,
                target_name=target_name,
                workspace_id=workspace_id,
            )
            session.run(
                """
                MATCH (a {name: $source_name, workspace_id: $workspace_id})
                MATCH (b {name: $target_name, workspace_id: $workspace_id})
                MERGE (a)-[c:CONFLICTS_WITH]->(b)
                ON CREATE SET c.created_at = timestamp(), c.workspace_id = $workspace_id
                """,
                source_name=source_name,
                target_name=target_name,
                workspace_id=workspace_id,
            )

    return has_conflict


def detect_all_conflicts(workspace_id: str) -> int:
    """Retroactive bulk pass over existing graph data for a workspace."""
    with get_driver().session() as session:
        result = session.run(
            """
            MATCH (a {workspace_id: $workspace_id})-[r1:SUPPORTS]->(b {workspace_id: $workspace_id})
            MATCH (a)-[r2:CONTRADICTS]->(b)
            WHERE r1.source_document_id <> r2.source_document_id
            SET r1.conflict_flag = true, r2.conflict_flag = true
            MERGE (a)-[c:CONFLICTS_WITH]->(b)
            ON CREATE SET c.created_at = timestamp(), c.workspace_id = $workspace_id
            RETURN count(*) AS conflicts_found
            """,
            workspace_id=workspace_id,
        )
        return result.single()["conflicts_found"]
