"""The qa_pipeline runs retrieval on the *standalone* (contextualized) question.

These pin the threading contract: when a follow-up is condensed, every retriever
and the synthesizer see the rewritten question — not the raw "what about him?" —
and the rewrite is surfaced on the result. With no history, the contextualizer is
skipped and the original question flows through unchanged, with no conversation
context handed to the synthesizer.

All external calls (contextualizer LLM, router, retrievers, synthesizer) are
stubbed — no LLM/DB.
"""
import pytest

import backend.core.qa_pipeline as qa


@pytest.fixture
def stub(monkeypatch):
    seen = {"graph_q": None, "vector_q": None, "synth_q": None, "synth_ctx": "__unset__"}

    async def fake_classify(question, workspace_id):
        return {"type": "hybrid", "reasoning": "stub"}

    async def fake_graph(question, workspace_id):
        seen["graph_q"] = question
        return {"cypher": "MATCH ...", "records": [{"name": "X"}], "entity_stats": [], "conflicts": []}

    async def fake_vector(question, workspace_id, top_k=8):
        seen["vector_q"] = question
        return {"chunks": [{"text": "c", "source_url": "u"}]}

    async def fake_synth(question, results, retrieval_type="hybrid", conversation_context="__unset__"):
        seen["synth_q"] = question
        seen["synth_ctx"] = conversation_context
        return {"answer": "ok", "key_entities": [], "insights": []}

    monkeypatch.setattr(qa, "classify_question", fake_classify)
    monkeypatch.setattr(qa, "run_graph_query", fake_graph)
    monkeypatch.setattr(qa, "run_vector_query", fake_vector)
    monkeypatch.setattr(qa, "synthesize_answer", fake_synth)
    return seen


async def test_no_history_skips_rewrite_and_passes_no_context(stub):
    res = await qa.answer_question("Who is Hinton?", "ws1")

    assert stub["graph_q"] == "Who is Hinton?"
    assert stub["vector_q"] == "Who is Hinton?"
    assert stub["synth_q"] == "Who is Hinton?"
    # No history → synthesize_answer called without the conversation_context kwarg.
    assert stub["synth_ctx"] == "__unset__"
    assert res["standalone_question"] is None
    assert res["is_followup"] is False


async def test_followup_retrieves_on_standalone_question(stub, monkeypatch):
    async def fake_contextualize(question, history_block):
        return {
            "standalone": "What is Geoffrey Hinton's later research work?",
            "rewritten": True,
            "is_followup": True,
        }

    monkeypatch.setattr(qa.conv, "contextualize_question", fake_contextualize)

    history = [{"question": "Who is Hinton?", "answer": "A deep learning pioneer."}]
    res = await qa.answer_question("what about his later work?", "ws1", history=history)

    standalone = "What is Geoffrey Hinton's later research work?"
    assert stub["graph_q"] == standalone, "graph must retrieve on the standalone question"
    assert stub["vector_q"] == standalone, "vector must retrieve on the standalone question"
    assert stub["synth_q"] == standalone
    # History present → synthesizer receives a non-empty conversation context.
    assert stub["synth_ctx"] and stub["synth_ctx"] != "__unset__"
    assert res["standalone_question"] == standalone
    assert res["is_followup"] is True


async def test_followup_without_rewrite_reports_null_standalone(stub, monkeypatch):
    async def fake_contextualize(question, history_block):
        # An already-standalone follow-up: returned unchanged.
        return {"standalone": question, "rewritten": False, "is_followup": False}

    monkeypatch.setattr(qa.conv, "contextualize_question", fake_contextualize)

    history = [{"question": "prior", "answer": "prior answer"}]
    res = await qa.answer_question("A fully self-contained question?", "ws1", history=history)

    assert res["standalone_question"] is None
    assert stub["graph_q"] == "A fully self-contained question?"
