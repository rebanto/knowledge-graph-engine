from backend.core.llm_client import generate_json
from backend.db.redis import get_cached_route, set_cached_route
from backend.core.observability import cache_hits_total, cache_misses_total

VALID_TYPES = {"graph", "vector", "hybrid"}

ROUTER_PROMPT = """Classify this research question so the knowledge graph engine can route it correctly.

The graph contains entities (Person, Organization, Paper, Concept, Event, Topic) connected by typed relationships.
The vector store contains embedded chunks of source documents.

Return ONLY JSON: {{"type": "graph"|"vector"|"hybrid", "reasoning": "one sentence"}}

Routing rules:
- "graph"  → questions about RELATIONSHIPS between specific named entities: who authored what, who
             collaborated with whom, what connects X to Y, how many edges, shortest path, citation
             chains, funding relationships, which papers contradict each other.
- "vector" → questions asking for KNOWLEDGE or CONTENT: summarize findings on topic X, what does
             research say about Y, latest developments, evidence for a claim, open problems.
- "hybrid" → questions needing BOTH: e.g. "summarize the work of researchers who collaborated with
             Person X", "which papers about Topic Y are most cited", "what institutions fund research
             into Concept Z and what do their papers say".

When in doubt between graph and hybrid, prefer hybrid — it runs both retrievers.

Question: {question}"""


async def classify_question(question: str, workspace_id: str = "") -> dict:
    # L2 cache: route classification is stable for 24h
    cached = await get_cached_route(workspace_id, question)
    if cached:
        cache_hits_total.labels(cache="route").inc()
        return cached

    cache_misses_total.labels(cache="route").inc()
    data = await generate_json(ROUTER_PROMPT.format(question=question))
    qtype = data.get("type")
    if qtype not in VALID_TYPES:
        qtype = "hybrid"
    result = {"type": qtype, "reasoning": data.get("reasoning", "")}

    await set_cached_route(workspace_id, question, result)
    return result
