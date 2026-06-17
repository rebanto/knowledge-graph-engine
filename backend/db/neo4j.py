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

async def merge_paper(paper_id: str, title: str, workspace_id: str, properties: dict = None):
    driver = await get_async_driver()
    props = {**(properties or {}), "name": title, "workspace_id": workspace_id}
    async with driver.session() as session:
        await session.run(
            """
            MERGE (n:Paper {arxiv_id: $paper_id})
            ON CREATE SET n += $props, n.created_at = timestamp(), n.source_count = 1
            ON MATCH SET n.source_count = n.source_count + 1, n.last_updated = timestamp()
            """,
            paper_id=paper_id,
            props=props,
        )


async def merge_node(label: str, name: str, workspace_id: str, properties: dict = None):
    driver = await get_async_driver()
    props = {**(properties or {}), "workspace_id": workspace_id}
    async with driver.session() as session:
        await session.run(
            f"""
            MERGE (n:{label} {{name: $name}})
            ON CREATE SET n += $props, n.created_at = timestamp(), n.source_count = 1
            ON MATCH SET n.source_count = n.source_count + 1, n.last_updated = timestamp()
            """,
            name=name,
            props=props,
        )


async def merge_edge(
    source_name: str,
    source_label: str,
    target_name: str,
    target_label: str,
    edge_type: str,
    workspace_id: str,
    properties: dict = None,
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

    async with driver.session() as session:
        await session.run(
            f"""
            MATCH {src_match}
            MATCH {tgt_match}
            MERGE (a)-[r:{edge_type}]->(b)
            ON CREATE SET r += $props, r.created_at = timestamp()
            ON MATCH SET r.last_updated = timestamp()
            """,
            src=source_name,
            tgt=target_name,
            props=props,
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
