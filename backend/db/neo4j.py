import os
from neo4j import GraphDatabase
from neo4j import AsyncGraphDatabase
from dotenv import load_dotenv

load_dotenv()

_driver = None
_async_driver = None

_URI = lambda: os.environ["NEO4J_URI"]
_AUTH = lambda: (os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])
_POOL = 50


# ── Sync driver — used by seed scripts and startup ────────────────────────────

def get_driver():
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(_URI(), auth=_AUTH(), max_connection_pool_size=_POOL)
    return _driver


def close_driver():
    global _driver
    if _driver:
        _driver.close()
        _driver = None


# ── Async driver — used by FastAPI routes and async ingestion workers ──────────

async def get_async_driver():
    global _async_driver
    if _async_driver is None:
        _async_driver = AsyncGraphDatabase.driver(
            _URI(),
            auth=_AUTH(),
            max_connection_pool_size=_POOL,
            connection_acquisition_timeout=5,
        )
    return _async_driver


async def close_async_driver():
    global _async_driver
    if _async_driver:
        await _async_driver.close()
        _async_driver = None


# ── Schema setup (sync — called once at startup) ───────────────────────────────

def setup_constraints():
    driver = get_driver()
    with driver.session() as session:
        for stmt in [
            "CREATE CONSTRAINT paper_arxiv_id IF NOT EXISTS FOR (n:Paper) REQUIRE n.arxiv_id IS UNIQUE",
            "CREATE CONSTRAINT person_name IF NOT EXISTS FOR (n:Person) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT org_name IF NOT EXISTS FOR (n:Organization) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT concept_name IF NOT EXISTS FOR (n:Concept) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT topic_name IF NOT EXISTS FOR (n:Topic) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT event_name IF NOT EXISTS FOR (n:Event) REQUIRE n.name IS UNIQUE",
        ]:
            session.run(stmt)


# ── Async write helpers — used by ingestion worker and graph retriever ─────────

# Idempotent list-append used to record which Postgres source(s) contributed a
# node or edge. Replayable: re-ingesting the same source is a no-op. The list is
# what makes source deletion possible — see remove_source_from_graph().
_ADD_SOURCE = """
    n.source_ids = CASE
        WHEN $source_id IS NULL THEN coalesce(n.source_ids, [])
        WHEN $source_id IN coalesce(n.source_ids, []) THEN n.source_ids
        ELSE coalesce(n.source_ids, []) + $source_id
    END,
    n.source_count = size(
        CASE
            WHEN $source_id IS NULL THEN coalesce(n.source_ids, [])
            WHEN $source_id IN coalesce(n.source_ids, []) THEN n.source_ids
            ELSE coalesce(n.source_ids, []) + $source_id
        END)
"""


async def merge_paper(
    paper_id: str, title: str, workspace_id: str,
    properties: dict = None, source_id: str = None,
):
    driver = await get_async_driver()
    props = {**(properties or {}), "name": title, "workspace_id": workspace_id}
    async with driver.session() as session:
        await session.run(
            f"""
            MERGE (n:Paper {{arxiv_id: $paper_id}})
            ON CREATE SET n += $props, n.created_at = timestamp()
            ON MATCH SET n += $props, n.last_updated = timestamp()
            SET {_ADD_SOURCE}
            """,
            paper_id=paper_id,
            props=props,
            source_id=source_id,
        )


async def merge_node(
    label: str, name: str, workspace_id: str,
    properties: dict = None, source_id: str = None,
):
    driver = await get_async_driver()
    props = {**(properties or {}), "workspace_id": workspace_id}
    async with driver.session() as session:
        await session.run(
            f"""
            MERGE (n:{label} {{name: $name}})
            ON CREATE SET n += $props, n.created_at = timestamp()
            ON MATCH SET n.last_updated = timestamp()
            SET {_ADD_SOURCE}
            """,
            name=name,
            props=props,
            source_id=source_id,
        )


async def merge_edge(
    source_name: str,
    source_label: str,
    target_name: str,
    target_label: str,
    edge_type: str,
    workspace_id: str,
    properties: dict = None,
    source_id: str = None,
):
    driver = await get_async_driver()
    props = {**(properties or {}), "workspace_id": workspace_id}

    src_match = (
        f"(a:{source_label} {{arxiv_id: $src}})"
        if source_label == "Paper"
        else f"(a:{source_label} {{name: $src}})"
    )
    tgt_match = (
        f"(b:{target_label} {{arxiv_id: $tgt}})"
        if target_label == "Paper"
        else f"(b:{target_label} {{name: $tgt}})"
    )

    # Same idempotent source-tracking as nodes, but applied to the relationship.
    add_source = _ADD_SOURCE.replace("n.", "r.")

    async with driver.session() as session:
        await session.run(
            f"""
            MATCH {src_match}
            MATCH {tgt_match}
            MERGE (a)-[r:{edge_type}]->(b)
            ON CREATE SET r += $props, r.created_at = timestamp()
            ON MATCH SET r.last_updated = timestamp()
            SET {add_source}
            """,
            src=source_name,
            tgt=target_name,
            props=props,
            source_id=source_id,
        )


async def is_paper_processed(paper_id: str) -> bool:
    driver = await get_async_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (n:Paper {arxiv_id: $paper_id}) RETURN n.entities_extracted AS done",
            paper_id=paper_id,
        )
        record = await result.single()
        return bool(record and record["done"])


async def mark_paper_processed(paper_id: str) -> None:
    driver = await get_async_driver()
    async with driver.session() as session:
        await session.run(
            "MATCH (n:Paper {arxiv_id: $paper_id}) SET n.entities_extracted = true",
            paper_id=paper_id,
        )


async def remove_source_from_graph(workspace_id: str, source_id: str) -> dict:
    """Detach a Postgres source's contribution from the knowledge graph.

    A node/edge may have been asserted by several sources, so we don't blindly
    delete: we drop this source_id from each node/edge's source_ids list, then
    delete only the ones left with no remaining source (orphans). Shared
    concepts that other live sources still reference are preserved.

    Edges are pruned first so relationships this source created between two
    surviving nodes are removed; then orphaned nodes are DETACH DELETEd.
    """
    driver = await get_async_driver()
    async with driver.session() as session:
        edge_res = await session.run(
            """
            MATCH ({workspace_id: $ws})-[r]->({workspace_id: $ws})
            WHERE $sid IN coalesce(r.source_ids, [])
            SET r.source_ids = [x IN r.source_ids WHERE x <> $sid]
            WITH r WHERE size(r.source_ids) = 0
            DELETE r
            RETURN count(*) AS removed
            """,
            ws=workspace_id, sid=source_id,
        )
        edges_removed = (await edge_res.single())["removed"]

        node_res = await session.run(
            """
            MATCH (n {workspace_id: $ws})
            WHERE $sid IN coalesce(n.source_ids, [])
            SET n.source_ids = [x IN n.source_ids WHERE x <> $sid],
                n.source_count = size([x IN n.source_ids WHERE x <> $sid])
            WITH n WHERE size(n.source_ids) = 0
            DETACH DELETE n
            RETURN count(*) AS removed
            """,
            ws=workspace_id, sid=source_id,
        )
        nodes_removed = (await node_res.single())["removed"]

    return {"nodes_removed": nodes_removed, "edges_removed": edges_removed}


async def delete_source_documents(workspace_id: str, document_urls: list[str]) -> int:
    """Remove all graph data contributed by a set of document URLs.

    Used by the workspace cleanup sweep, where only the document URLs of
    orphaned ingestion jobs are known (the source row — and its source_id — is
    already gone, so remove_source_from_graph can't be used). Steps:
      1. Collect the arxiv_id of each matching Paper for edge cleanup.
      2. DETACH DELETE the Paper nodes (removes Paper + all its relationships).
      3. Delete any remaining entity->entity edges tagged with those doc IDs.
      4. Delete non-Paper entity nodes that now have no edges at all.

    Scoped by workspace_id so deleting documents in one workspace never removes
    a Paper another workspace owns. Returns the number of Paper nodes deleted.
    """
    if not document_urls:
        return 0

    driver = await get_async_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            UNWIND $urls AS url
            MATCH (p:Paper) WHERE p.workspace_id = $ws AND p.url = url
            RETURN p.arxiv_id AS doc_id
            """,
            urls=document_urls, ws=workspace_id,
        )
        records = await result.data()
        doc_ids = [r["doc_id"] for r in records if r.get("doc_id")]

        await session.run(
            """
            UNWIND $urls AS url
            MATCH (p:Paper) WHERE p.workspace_id = $ws AND p.url = url
            DETACH DELETE p
            """,
            urls=document_urls, ws=workspace_id,
        )
        deleted = len(doc_ids)

        if doc_ids:
            await session.run(
                """
                UNWIND $doc_ids AS did
                MATCH ()-[r]->() WHERE r.source_document_id = did DELETE r
                """,
                doc_ids=doc_ids,
            )

        await session.run(
            "MATCH (n {workspace_id: $ws}) WHERE NOT n:Paper AND NOT (n)--() DELETE n",
            ws=workspace_id,
        )

        return deleted


async def get_node_count() -> int:
    driver = await get_async_driver()
    async with driver.session() as session:
        result = await session.run("MATCH (n) RETURN count(n) AS count")
        record = await result.single()
        return record["count"]


async def get_edge_count() -> int:
    driver = await get_async_driver()
    async with driver.session() as session:
        result = await session.run("MATCH ()-[r]->() RETURN count(r) AS count")
        record = await result.single()
        return record["count"]


# ── Sync helpers preserved for seed_arxiv.py ──────────────────────────────────

def merge_paper_sync(paper_id: str, title: str, workspace_id: str, properties: dict = None):
    props = {**(properties or {}), "name": title, "workspace_id": workspace_id}
    with get_driver().session() as session:
        session.run(
            """
            MERGE (n:Paper {arxiv_id: $paper_id})
            ON CREATE SET n += $props, n.created_at = timestamp(), n.source_count = 1
            ON MATCH SET n.source_count = n.source_count + 1, n.last_updated = timestamp()
            """,
            paper_id=paper_id, props=props,
        )


def merge_node_sync(label: str, name: str, workspace_id: str, properties: dict = None):
    props = {**(properties or {}), "workspace_id": workspace_id}
    with get_driver().session() as session:
        session.run(
            f"""
            MERGE (n:{label} {{name: $name}})
            ON CREATE SET n += $props, n.created_at = timestamp(), n.source_count = 1
            ON MATCH SET n.source_count = n.source_count + 1, n.last_updated = timestamp()
            """,
            name=name, props=props,
        )


def merge_edge_sync(
    source_name, source_label, target_name, target_label,
    edge_type, workspace_id, properties=None,
):
    props = {**(properties or {}), "workspace_id": workspace_id}
    src_match = (
        f"(a:{source_label} {{arxiv_id: $src}})"
        if source_label == "Paper" else f"(a:{source_label} {{name: $src}})"
    )
    tgt_match = (
        f"(b:{target_label} {{arxiv_id: $tgt}})"
        if target_label == "Paper" else f"(b:{target_label} {{name: $tgt}})"
    )
    with get_driver().session() as session:
        session.run(
            f"""
            MATCH {src_match} MATCH {tgt_match}
            MERGE (a)-[r:{edge_type}]->(b)
            ON CREATE SET r += $props, r.created_at = timestamp()
            ON MATCH SET r.last_updated = timestamp()
            """,
            src=source_name, tgt=target_name, props=props,
        )


def is_paper_processed_sync(paper_id: str) -> bool:
    with get_driver().session() as session:
        result = session.run(
            "MATCH (n:Paper {arxiv_id: $paper_id}) RETURN n.entities_extracted AS done",
            paper_id=paper_id,
        )
        record = result.single()
        return bool(record and record["done"])


def mark_paper_processed_sync(paper_id: str) -> None:
    with get_driver().session() as session:
        session.run(
            "MATCH (n:Paper {arxiv_id: $paper_id}) SET n.entities_extracted = true",
            paper_id=paper_id,
        )
