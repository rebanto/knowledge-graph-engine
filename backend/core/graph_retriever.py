import re
from backend.core.llm_client import generate_json
from backend.db.neo4j import get_async_driver
from backend.db.redis import get_cached_cypher, set_cached_cypher
from backend.core.resilience import neo4j_breaker, CircuitBreakerError
from backend.core.observability import cache_hits_total, cache_misses_total

SCHEMA = """Node labels: Person, Organization, Paper, Concept, Event, Topic

Relationship types (always source → target):
  Authorship / citation / people:
    (Person)-[:AUTHORED]->(Paper)
    (Person)-[:COLLABORATED_WITH]->(Person)
    (Person)-[:AFFILIATED_WITH]->(Organization)
    (Paper)-[:CITED]->(Paper)
  Paper ↔ its content (these connect papers that share a concept/topic):
    (Paper)-[:ABOUT]->(Topic)            ← topic / research area / arxiv category
    (Paper)-[:MENTIONS]->(Concept)       ← method, dataset, metric, architecture…
    (Paper)-[:AFFILIATED_WITH]->(Organization)
    (Paper)-[:PRESENTED_AT]->(Event)
    (Paper)-[:PUBLISHED_IN]->(Topic)
  Conceptual structure (Concept → Concept unless noted):
    (Concept)-[:PROPOSES|USES|EXTENDS|IMPROVES|COMPARED_TO|EVALUATED_ON|PART_OF|RELATED_TO]->(Concept)
    (Concept)-[:APPLIED_TO]->(Topic|Concept)
  Funding & claims:
    (Organization)-[:FUNDED_BY]->(Organization)
    (Concept)-[:SUPPORTS]->(Concept)
    (Concept)-[:CONTRADICTS]->(Concept)
    (Concept)-[:CONFLICTS_WITH]->(Concept)   ← auto-created when two sources disagree

To find papers related to a concept/topic: (p:Paper)-[:MENTIONS|ABOUT]->(c {name: ...}).
To find papers related to each other: (p1:Paper)-[:MENTIONS|ABOUT]->(c)<-[:MENTIONS|ABOUT]-(p2:Paper).

Node properties:
  ALL: name (string), workspace_id (string), source_count (int)
  Paper: arxiv_id, url, published (ISO datetime), categories (string)

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


async def question_to_cypher(question: str, workspace_id: str) -> str:
    data = await generate_json(
        CYPHER_PROMPT.format(schema=SCHEMA, workspace_id=workspace_id, question=question)
    )
    cypher = data.get("cypher", "").strip()
    if not cypher or FORBIDDEN.search(cypher):
        raise UnsafeQueryError(f"Rejected unsafe or empty Cypher: {cypher!r}")
    return cypher


async def _exec(cypher: str, params: dict | None = None, timeout: int = 15) -> list[dict]:
    # Check circuit breaker before attempting Neo4j
    try:
        neo4j_breaker.call(lambda: None)
    except CircuitBreakerError:
        raise

    driver = await get_async_driver()
    async with driver.session() as session:
        result = await session.run(cypher, **(params or {}))
        records = await result.data()
        return records


async def _entity_degree_context(workspace_id: str, names: list[str]) -> list[dict]:
    if not names:
        return []
    try:
        return await _exec(
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
    except Exception:
        return []


async def run_graph_query(question: str, workspace_id: str) -> dict:
    cypher = await question_to_cypher(question, workspace_id)

    # L2 cache: Cypher results are cached for 5 min (graph changes slowly)
    cached_records = await get_cached_cypher(cypher)
    if cached_records is not None:
        cache_hits_total.labels(cache="cypher").inc()
        return {"cypher": cypher, "records": cached_records, "entity_stats": []}

    cache_misses_total.labels(cache="cypher").inc()
    records = await _exec(cypher)

    # Pull entity-looking strings for the secondary stats pass
    candidate_names: list[str] = []
    for row in records[:40]:
        for v in row.values():
            if isinstance(v, str) and 2 < len(v) < 100 and not v.startswith("http") and not v.isupper():
                candidate_names.append(v)

    unique_names = list(dict.fromkeys(candidate_names))[:20]
    entity_stats = await _entity_degree_context(workspace_id, unique_names)

    await set_cached_cypher(cypher, records)

    return {"cypher": cypher, "records": records, "entity_stats": entity_stats}
