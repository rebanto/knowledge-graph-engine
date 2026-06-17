from backend.core.router import classify_question
from backend.core.graph_retriever import run_graph_query, UnsafeQueryError
from backend.core.vector_retriever import run_vector_query
from backend.core.synthesizer import synthesize_answer
from backend.db.redis import get_cached_answer, set_cached_answer


def answer_question(question: str, workspace_id: str, use_cache: bool = True) -> dict:
    if use_cache:
        cached = get_cached_answer(workspace_id, question)
        if cached:
            return {**cached, "cached": True}

    routing = classify_question(question)
    qtype = routing["type"]

    graph_records: list[dict] = []
    entity_stats: list[dict] = []
    vector_chunks: list[dict] = []
    cypher = None
    results: dict = {}

    if qtype in ("graph", "hybrid"):
        try:
            graph_result = run_graph_query(question, workspace_id)
            cypher = graph_result["cypher"]
            graph_records = graph_result["records"]
            entity_stats = graph_result.get("entity_stats", [])
            results["graph_records"] = graph_records
            if entity_stats:
                # Give the synthesizer degree context so it can mention citation counts etc.
                results["entity_degree_context"] = entity_stats
        except UnsafeQueryError:
            pass

    if qtype in ("vector", "hybrid"):
        # Increase to 8 chunks for richer context
        vector_result = run_vector_query(question, workspace_id, top_k=8)
        vector_chunks = vector_result["chunks"]
        results["vector_passages"] = vector_chunks

    synthesis = synthesize_answer(question, results, retrieval_type=qtype)

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
        set_cached_answer(workspace_id, question, result)

    return result
