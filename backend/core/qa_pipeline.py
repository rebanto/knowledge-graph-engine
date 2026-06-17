import asyncio
from backend.core.router import classify_question
from backend.core.graph_retriever import run_graph_query, UnsafeQueryError
from backend.core.vector_retriever import run_vector_query
from backend.core.synthesizer import synthesize_answer
from backend.core.resilience import CircuitBreakerError
from backend.db.redis import (
    get_cached_answer, set_cached_answer,
    acquire_inflight_lock, release_inflight_lock, wait_for_inflight,
)
from backend.core.observability import cache_hits_total, cache_misses_total


async def answer_question(question: str, workspace_id: str, use_cache: bool = True) -> dict:
    # ── L2 cache: check for a previously computed answer ──────────────────────
    if use_cache:
        cached = await get_cached_answer(workspace_id, question)
        if cached:
            cache_hits_total.labels(cache="answer").inc()
            return {**cached, "cached": True}

    cache_misses_total.labels(cache="answer").inc()

    # ── In-flight deduplication: if another request is already answering this
    # identical question, wait for it to finish and return the cached result.
    acquired = await acquire_inflight_lock(workspace_id, question)
    if not acquired:
        result = await wait_for_inflight(workspace_id, question)
        if result:
            return {**result, "cached": True}
        # Timed out waiting — fall through and compute independently

    try:
        return await _compute_answer(question, workspace_id, use_cache)
    finally:
        await release_inflight_lock(workspace_id, question)


async def _compute_answer(question: str, workspace_id: str, use_cache: bool) -> dict:
    routing = await classify_question(question, workspace_id)
    qtype = routing["type"]

    graph_records: list[dict] = []
    entity_stats: list[dict] = []
    vector_chunks: list[dict] = []
    cypher = None
    results: dict = {}

    # ── Run graph and vector retrieval in parallel for hybrid queries ──────────
    async def _graph():
        nonlocal cypher, graph_records, entity_stats
        try:
            graph_result = await run_graph_query(question, workspace_id)
            cypher = graph_result["cypher"]
            graph_records = graph_result["records"]
            entity_stats = graph_result.get("entity_stats", [])
        except (UnsafeQueryError, CircuitBreakerError):
            pass  # Degrade gracefully — vector search still proceeds

    async def _vector():
        nonlocal vector_chunks
        try:
            vector_result = await run_vector_query(question, workspace_id, top_k=8)
            vector_chunks = vector_result["chunks"]
        except Exception:
            pass  # Degrade gracefully — graph results still used

    if qtype == "hybrid":
        await asyncio.gather(_graph(), _vector())
    elif qtype == "graph":
        await _graph()
    else:
        await _vector()

    if graph_records:
        results["graph_records"] = graph_records
    if entity_stats:
        results["entity_degree_context"] = entity_stats
    if vector_chunks:
        results["vector_passages"] = vector_chunks

    synthesis = await synthesize_answer(question, results, retrieval_type=qtype)

    result = {
        "type": qtype,
        "reasoning": routing["reasoning"],
        "cypher": cypher,
        "graph_records": graph_records,
        "vector_chunks": vector_chunks,
        "answer": synthesis["answer"],
        "key_entities": synthesis.get("key_entities", []),
        "insights": synthesis.get("insights", []),
        "cached": False,
    }

    if use_cache:
        await set_cached_answer(workspace_id, question, result)

    return result
