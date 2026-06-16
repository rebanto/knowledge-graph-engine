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
    vector_chunks: list[dict] = []
    cypher = None
    results: dict = {}

    if qtype in ("graph", "hybrid"):
        try:
            graph_result = run_graph_query(question, workspace_id)
            cypher = graph_result["cypher"]
            graph_records = graph_result["records"]
            results["graph"] = graph_records
        except UnsafeQueryError:
            pass

    if qtype in ("vector", "hybrid"):
        vector_result = run_vector_query(question, workspace_id)
        vector_chunks = vector_result["chunks"]
        results["vector"] = vector_chunks

    answer = synthesize_answer(question, results)

    result = {
        "type": qtype,
        "reasoning": routing["reasoning"],
        "cypher": cypher,
        "graph_records": graph_records,
        "vector_chunks": vector_chunks,
        "answer": answer,
        "cached": False,
    }

    if use_cache:
        set_cached_answer(workspace_id, question, result)

    return result
