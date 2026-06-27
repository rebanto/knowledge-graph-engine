import asyncio
from backend.core.router import classify_question
from backend.core.graph_retriever import run_graph_query, UnsafeQueryError
from backend.core.vector_retriever import run_vector_query
from backend.core.synthesizer import synthesize_answer
from backend.core import conversation as conv
from backend.core.resilience import CircuitBreakerError
from backend.core.observability import cache_misses_total


async def answer_question(
    question: str,
    workspace_id: str,
    *,
    history: list[dict] | None = None,
    summary: str | None = None,
) -> dict:
    # Answer caching is intentionally absent: a cached answer taken before a
    # new source finishes ingesting would silently omit that source's content,
    # making it look like the engine doesn't know about the new data.
    # Embedding, route-classification, and Cypher caches still apply — only the
    # final synthesised answer is always freshly computed.
    #
    # `history` (oldest→newest {question, answer}) and `summary` carry prior
    # conversation context; when both are empty this is a plain single-shot
    # question and the contextualizer is skipped (no added LLM call).
    cache_misses_total.labels(cache="answer").inc()
    return await _compute_answer(question, workspace_id, history or [], summary)


async def _compute_answer(
    question: str,
    workspace_id: str,
    history: list[dict],
    summary: str | None,
) -> dict:
    # ── Resolve follow-up into a standalone question before anything else ──────
    # Routing, Cypher generation, and embedding all retrieve far better on a
    # self-contained question. The whole pipeline downstream runs on `standalone`.
    history_block = conv.build_history_block(conv.window_turns(history), summary)
    ctx = await conv.contextualize_question(question, history_block)
    standalone = ctx["standalone"]

    routing = await classify_question(standalone, workspace_id)
    qtype = routing["type"]

    graph_records: list[dict] = []
    entity_stats: list[dict] = []
    conflicts: list[dict] = []
    influence: list[dict] = []
    vector_chunks: list[dict] = []
    cypher = None
    results: dict = {}

    # ── Run graph and vector retrieval in parallel for hybrid queries ──────────
    async def _graph():
        nonlocal cypher, graph_records, entity_stats, conflicts, influence
        try:
            graph_result = await run_graph_query(standalone, workspace_id)
            cypher = graph_result["cypher"]
            graph_records = graph_result["records"]
            entity_stats = graph_result.get("entity_stats", [])
            conflicts = graph_result.get("conflicts", [])
            influence = graph_result.get("influence", [])
        except (UnsafeQueryError, CircuitBreakerError):
            pass  # Degrade gracefully — vector search still proceeds

    async def _vector():
        nonlocal vector_chunks
        try:
            vector_result = await run_vector_query(standalone, workspace_id, top_k=8)
            vector_chunks = vector_result["chunks"]
        except Exception:
            pass  # Degrade gracefully — graph results still used

    if qtype == "hybrid":
        await asyncio.gather(_graph(), _vector())
    elif qtype == "graph":
        await _graph()
        # Safety net: the router is an LLM and sometimes sends a content question
        # to the graph (or the graph genuinely has nothing on it). Rather than
        # answer "no information" while the answer sits in the vector store, fall
        # back to vector search when the graph came back empty.
        if not graph_records and not entity_stats:
            await _vector()
    else:
        await _vector()
        # Symmetric fallback: a relationship question misrouted to vector still
        # gets a chance at the graph instead of returning nothing.
        if not vector_chunks:
            await _graph()

    if graph_records:
        results["graph_records"] = graph_records
    if entity_stats:
        results["entity_degree_context"] = entity_stats
    if conflicts:
        # Hand the disputed claims to the synthesizer so the prose calls them out.
        results["conflicts"] = conflicts
    if influence:
        # PageRank centrality for the answer's entities — lets the synthesizer
        # say which entity is most influential in the graph, not just present.
        results["entity_influence"] = influence
    if vector_chunks:
        results["vector_passages"] = vector_chunks

    # Only hand the synthesizer conversation context when there actually is some,
    # so the single-shot path keeps the original call signature (and old test
    # stubs keep working).
    synth_kwargs = {"conversation_context": history_block} if history_block else {}
    synthesis = await synthesize_answer(
        standalone, results, retrieval_type=qtype, **synth_kwargs
    )

    return {
        "type": qtype,
        "reasoning": routing["reasoning"],
        "cypher": cypher,
        "graph_records": graph_records,
        "vector_chunks": vector_chunks,
        "conflicts": conflicts,
        "answer": synthesis["answer"],
        "key_entities": synthesis.get("key_entities", []),
        "insights": synthesis.get("insights", []),
        "cached": False,
        # Surface the rewrite so the route can persist it and the UI can show it.
        # standalone_question is None when no rewrite happened (first turn or an
        # already-standalone follow-up).
        "standalone_question": standalone if ctx["rewritten"] else None,
        "is_followup": ctx["is_followup"],
    }
