from backend.db.neo4j import get_async_driver

OPPOSITE = {"SUPPORTS": "CONTRADICTS", "CONTRADICTS": "SUPPORTS"}


async def check_and_flag_conflict(
    source_name: str,
    target_name: str,
    edge_type: str,
    source_document_id: str,
    workspace_id: str,
) -> bool:
    opposite = OPPOSITE.get(edge_type)
    if not opposite:
        return False

    driver = await get_async_driver()
    async with driver.session() as session:
        result = await session.run(
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
        record = await result.single()
        has_conflict = record["count"] > 0

        if has_conflict:
            await session.run(
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
            await session.run(
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


async def detect_all_conflicts(workspace_id: str) -> int:
    """Retroactive bulk conflict detection pass for a workspace."""
    driver = await get_async_driver()
    async with driver.session() as session:
        result = await session.run(
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
        record = await result.single()
        return record["conflicts_found"]
