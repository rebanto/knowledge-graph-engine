"""Tests for the qa_pipeline cross-retriever fallback.

The query router is an LLM and occasionally misclassifies a content question as a
relationship question (or vice versa). Before the fix, a content question routed
to "graph" never consulted the vector store, so it answered "no information" even
though the answer was sitting in ChromaDB. These tests pin the fallback: when the
routed retriever comes back empty, the other one runs before synthesis.

All external calls (router, retrievers, synthesizer) are stubbed — no LLM/DB.
"""
import pytest

import backend.core.qa_pipeline as qa


@pytest.fixture
def stub(monkeypatch):
    calls = {"graph": 0, "vector": 0}
    state = {"graph_records": [], "vector_chunks": [], "route": "graph"}

    async def fake_classify(question, workspace_id):
        return {"type": state["route"], "reasoning": "stubbed"}

    async def fake_graph(question, workspace_id):
        calls["graph"] += 1
        return {"cypher": "MATCH ...", "records": state["graph_records"], "entity_stats": []}

    async def fake_vector(question, workspace_id, top_k=8):
        calls["vector"] += 1
        return {"chunks": state["vector_chunks"]}

    captured = {}

    async def fake_synth(question, results, retrieval_type="hybrid"):
        captured["results"] = results
        return {"answer": "ok", "key_entities": [], "insights": []}

    monkeypatch.setattr(qa, "classify_question", fake_classify)
    monkeypatch.setattr(qa, "run_graph_query", fake_graph)
    monkeypatch.setattr(qa, "run_vector_query", fake_vector)
    monkeypatch.setattr(qa, "synthesize_answer", fake_synth)
    return calls, state, captured


async def test_graph_route_empty_falls_back_to_vector(stub):
    calls, state, captured = stub
    state["route"] = "graph"
    state["graph_records"] = []                      # graph finds nothing
    state["vector_chunks"] = [{"text": "the answer", "source_url": "u"}]

    res = await qa.answer_question("What does my document say?", "ws1")

    assert calls["vector"] == 1, "vector fallback must run when graph is empty"
    assert "vector_passages" in captured["results"]
    assert res["vector_chunks"]


async def test_graph_route_with_results_does_not_fall_back(stub):
    calls, state, _ = stub
    state["route"] = "graph"
    state["graph_records"] = [{"name": "X"}]         # graph has data
    state["vector_chunks"] = [{"text": "unused"}]

    await qa.answer_question("who connects to X?", "ws1")

    assert calls["graph"] == 1
    assert calls["vector"] == 0, "no fallback when the routed retriever succeeded"


async def test_vector_route_empty_falls_back_to_graph(stub):
    calls, state, captured = stub
    state["route"] = "vector"
    state["vector_chunks"] = []                       # vector finds nothing
    state["graph_records"] = [{"name": "Y", "rel": "AUTHORED"}]

    await qa.answer_question("summarize Y", "ws1")

    assert calls["graph"] == 1, "graph fallback must run when vector is empty"
    assert "graph_records" in captured["results"]
