import re
from backend.core.llm_client import generate_json
from backend.db.neo4j import get_driver

SCHEMA = """Node labels: Person, Organization, Paper, Concept, Event, Topic

Relationship types (always source → target):
  (Person)-[:AUTHORED]->(Paper)
  (Paper)-[:CITED]->(Paper)
  (Organization)-[:FUNDED_BY]->(Organization)
  (Person)-[:COLLABORATED_WITH]->(Person)
  (Paper)-[:PUBLISHED_IN]->(Topic)
  (Concept)-[:SUPPORTS]->(Concept)
  (Concept)-[:CONTRADICTS]->(Concept)
  (Concept)-[:CONFLICTS_WITH]->(Concept)   ← auto-created when two sources disagree

Node properties:
  ALL: name (string), workspace_id (string)
  Paper: arxiv_id, url, published (ISO datetime), categories (list)

Edge properties:
  ALL: source_document_id, confidence (0.0–1.0), workspace_id
  SUPPORTS/CONTRADICTS: conflict_flag (true = disputed claim)

Domain-agnostic: nodes cover any research domain — not just AI/ML."""

CYPHER_PROMPT = """Translate this research question into a read-only Cypher query.

Graph schema:
{schema}

Workspace filter — EVERY node pattern MUST include: {{workspace_id: "{workspace_id}"}}

Query design guidelines:
- Read-only: MATCH / OPTIONAL MATCH / WHERE / WITH / RETURN / ORDER BY / LIMIT only.
  Never use CREATE, MERGE, DELETE, SET, REMOVE, CALL, or FOREACH.
- Always return named columns — never return whole node/relationship objects.
- Always include type(r) when returning relationships so the result is self-explanatory.
- For "how connected / what path" questions: use variable-length paths [*1..4] and RETURN the node names along the path.
- For "who collaborated / worked with" questions: traverse both COLLABORATED_WITH and co-AUTHORED paths (two people share a paper).
- For "most cited / influential" questions: count incoming [:CITED] edges, ORDER BY desc.
- For "recent / timeline" questions: include p.published in the RETURN and ORDER BY p.published DESC.
- For "concepts / topics / ideas" questions: include PUBLISHED_IN, SUPPORTS, CONTRADICTS edges.
- For "funding / institutions" questions: traverse FUNDED_BY and Person→AUTHORED→Paper→source edges.
- For "conflict / contradiction" questions: filter on conflict_flag = true or use CONFLICTS_WITH edges.
- Return 30–50 rows. Use aggregation (COUNT, COLLECT) when counting.
- When appropriate, ORDER BY a meaningful column so the synthesizer sees ranked data.

Return ONLY valid JSON: {{"cypher": "MATCH ..."}}

Research question: {question}"""

FORBIDDEN = re.compile(
    r"\b(CREATE|MERGE|DELETE|REMOVE|SET|DROP|DETACH|CALL|LOAD\s+CSV|FOREACH)\b",
    re.IGNORECASE,
)


class UnsafeQueryError(Exception):
    pass


def question_to_cypher(question: str, workspace_id: str) -> str:
    data = generate_json(
        CYPHER_PROMPT.format(schema=SCHEMA, workspace_id=workspace_id, question=question)
    )
    cypher = data.get("cypher", "").strip()
    if not cypher or FORBIDDEN.search(cypher):
        raise UnsafeQueryError(f"Rejected unsafe or empty Cypher: {cypher!r}")
    return cypher


def _exec(cypher: str, params: dict | None = None, timeout: int = 15) -> list[dict]:
    with get_driver().session() as session:
        result = session.run(cypher, **(params or {}), timeout=timeout)
        return [record.data() for record in result]


def _entity_degree_context(workspace_id: str, names: list[str]) -> list[dict]:
    """
    For the top entities found in main query results, fetch their degree so the
    synthesizer can state things like "Paper X is cited by N works in this corpus."
    """
    if not names:
        return []
    try:
        rows = _exec(
            """
            UNWIND $names AS nm
            MATCH (n {name: nm, workspace_id: $ws})
            OPTIONAL MATCH (n)-[r]-()
            WITH n, labels(n)[0] AS lbl, count(r) AS deg
            RETURN n.name AS name, lbl AS type, deg AS degree
            ORDER BY deg DESC
            LIMIT 20
            """,
            {"names": names[:20], "ws": workspace_id},
            timeout=8,
        )
        return rows
    except Exception:
        return []


def run_graph_query(question: str, workspace_id: str) -> dict:
    cypher = question_to_cypher(question, workspace_id)
    records = _exec(cypher)

    # Pull out entity-looking string values for the secondary stats pass
    candidate_names: list[str] = []
    for row in records[:40]:
        for v in row.values():
            if isinstance(v, str) and 2 < len(v) < 100 and not v.startswith("http") and not v.isupper():
                candidate_names.append(v)

    unique_names = list(dict.fromkeys(candidate_names))[:20]
    entity_stats = _entity_degree_context(workspace_id, unique_names)

    return {
        "cypher": cypher,
        "records": records,
        "entity_stats": entity_stats,
    }
