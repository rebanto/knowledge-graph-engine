import re
from backend.core.llm_client import generate_json
from backend.db.neo4j import get_driver

# Locally we run Cypher against Neo4j; this translates to Gremlin against
# Neptune in Phase 5 (see CLAUDE.md). The schema below is domain-agnostic.
SCHEMA_DESCRIPTION = """Node labels: Person, Organization, Paper, Concept, Event, Topic
Edge directions (always source -> target, exactly as listed):
  (Person)-[:AUTHORED]->(Paper)
  (Paper)-[:CITED]->(Paper)
  (Organization)-[:FUNDED_BY]->(Organization)
  (Person)-[:COLLABORATED_WITH]->(Person)
  (Paper)-[:PUBLISHED_IN]->(Topic)
  (Concept)-[:SUPPORTS]->(Concept)
  (Concept)-[:CONTRADICTS]->(Concept)
Node properties: name (Paper nodes also have arxiv_id, url, published), workspace_id
Edge properties: source_document_id, confidence, context, workspace_id"""

CYPHER_PROMPT = """Translate this question into a read-only Cypher query against a Neo4j graph.

Schema:
{schema}

Rules:
- Read-only: MATCH/OPTIONAL MATCH/WHERE/WITH/RETURN/ORDER BY/LIMIT only. Never write, delete, or call procedures.
- Always filter every node pattern by workspace_id: "{workspace_id}"
- Return real properties (e.g. n.name, type(r), r.confidence) — never whole node/relationship objects.
- Add a LIMIT (25 by default) unless the question asks for a count.

Return ONLY JSON: {{"cypher": "MATCH ... RETURN ..."}}

Question: {question}"""

FORBIDDEN_PATTERN = re.compile(
    r"\b(CREATE|MERGE|DELETE|REMOVE|SET|DROP|DETACH|CALL|LOAD\s+CSV|FOREACH)\b",
    re.IGNORECASE,
)


class UnsafeQueryError(Exception):
    pass


def question_to_cypher(question: str, workspace_id: str) -> str:
    data = generate_json(
        CYPHER_PROMPT.format(schema=SCHEMA_DESCRIPTION, workspace_id=workspace_id, question=question)
    )
    cypher = data.get("cypher", "").strip()
    if not cypher or FORBIDDEN_PATTERN.search(cypher):
        raise UnsafeQueryError(f"Rejected unsafe or empty Cypher: {cypher!r}")
    return cypher


def run_graph_query(question: str, workspace_id: str) -> dict:
    cypher = question_to_cypher(question, workspace_id)
    with get_driver().session() as session:
        result = session.run(cypher, timeout=10)
        records = [record.data() for record in result]
    return {"cypher": cypher, "records": records}
