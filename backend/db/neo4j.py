import os
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()

_driver = None


def get_driver():
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
        )
    return _driver


def close_driver():
    global _driver
    if _driver:
        _driver.close()
        _driver = None


def setup_constraints():
    driver = get_driver()
    with driver.session() as session:
        constraints = [
            "CREATE CONSTRAINT paper_arxiv_id IF NOT EXISTS FOR (n:Paper) REQUIRE n.arxiv_id IS UNIQUE",
            "CREATE CONSTRAINT person_name IF NOT EXISTS FOR (n:Person) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT org_name IF NOT EXISTS FOR (n:Organization) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT concept_name IF NOT EXISTS FOR (n:Concept) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT topic_name IF NOT EXISTS FOR (n:Topic) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT event_name IF NOT EXISTS FOR (n:Event) REQUIRE n.name IS UNIQUE",
        ]
        for stmt in constraints:
            session.run(stmt)


def merge_paper(paper_id: str, title: str, workspace_id: str, properties: dict = None):
    driver = get_driver()
    props = {**(properties or {}), "name": title, "workspace_id": workspace_id}
    with driver.session() as session:
        session.run(
            """
            MERGE (n:Paper {arxiv_id: $paper_id})
            ON CREATE SET n += $props, n.created_at = timestamp(), n.source_count = 1
            ON MATCH SET n.source_count = n.source_count + 1, n.last_updated = timestamp()
            """,
            paper_id=paper_id,
            props=props,
        )


def merge_node(label: str, name: str, workspace_id: str, properties: dict = None):
    driver = get_driver()
    props = {**(properties or {}), "workspace_id": workspace_id}
    with driver.session() as session:
        session.run(
            f"""
            MERGE (n:{label} {{name: $name}})
            ON CREATE SET n += $props, n.created_at = timestamp(), n.source_count = 1
            ON MATCH SET n.source_count = n.source_count + 1, n.last_updated = timestamp()
            """,
            name=name,
            props=props,
        )


def merge_edge(
    source_name: str,
    source_label: str,
    target_name: str,
    target_label: str,
    edge_type: str,
    workspace_id: str,
    properties: dict = None,
):
    driver = get_driver()
    props = {**(properties or {}), "workspace_id": workspace_id}

    # Paper nodes are matched by arxiv_id stored in name field for edges
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

    with driver.session() as session:
        session.run(
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


def get_node_count() -> int:
    with get_driver().session() as session:
        result = session.run("MATCH (n) RETURN count(n) AS count")
        return result.single()["count"]


def get_edge_count() -> int:
    with get_driver().session() as session:
        result = session.run("MATCH ()-[r]->() RETURN count(r) AS count")
        return result.single()["count"]
