"""Multi-agent orchestrator logic, with every external call stubbed (no LLM/DB).

Pins the deep-research contract:
  - the planner's decomposition fans out to one sub-agent per sub-question, each
    pinned to its route through the EXISTING qa pipeline;
  - sub-agent evidence is unioned (conflicts de-duped) for the judge;
  - the faithfulness judge's verdicts become the surfaced trust score;
  - progress is emitted through the on_event callback the SSE route relies on;
  - a planner that returns nothing degrades to a single hybrid sub-question
    instead of failing.
"""
import backend.core.orchestrator as orch


def _plan(*subs):
    async def fake_generate_json(prompt):
        return {"subquestions": list(subs)}
    return fake_generate_json


async def _fake_answer_factory(by_question):
    async def fake_answer(question, workspace_id, *, force_route=None):
        return by_question[question]
    return fake_answer


def test_trust_scoring():
    claims = [{"claim": "a", "supported": True},
              {"claim": "b", "supported": True},
              {"claim": "c", "supported": False}]
    t = orch._trust(claims)
    assert t["supported"] == 2 and t["total"] == 3
    assert t["score"] == round(2 / 3, 3)
    assert t["unsupported_claims"] == ["c"]


def test_trust_no_claims_is_vacuously_grounded():
    # No checkable claims → None, never a fake 0% that looks like a hallucination.
    assert orch._trust([])["score"] is None


def test_aggregate_evidence_unions_and_dedupes_conflicts():
    subs = [
        {"graph_records": [{"a": 1}], "vector_chunks": [{"t": "x"}],
         "conflicts": [{"source": "A", "target": "B"}]},
        {"graph_records": [{"a": 2}], "vector_chunks": [],
         "conflicts": [{"source": "A", "target": "B"}, {"source": "C", "target": "D"}]},
    ]
    ev = orch._aggregate_evidence(subs)
    assert len(ev["graph_records"]) == 2
    assert len(ev["vector_passages"]) == 1
    # (A,B) appears in both sub-agents but is counted once.
    assert len(ev["conflicts"]) == 2


def test_dedupe_entities_case_insensitive():
    subs = [
        {"key_entities": [{"name": "Hinton", "type": "Person"}]},
        {"key_entities": [{"name": "hinton", "type": "Person"},
                          {"name": "Bengio", "type": "Person"}]},
    ]
    names = [e["name"] for e in orch._dedupe_entities(subs)]
    assert names == ["Hinton", "Bengio"]


async def test_plan_research_falls_back_to_single_hybrid(monkeypatch):
    async def empty_plan(prompt):
        return {"subquestions": []}
    monkeypatch.setattr(orch, "generate_json", empty_plan)
    plan = await orch.plan_research("Who funds X?", "ws1")
    assert len(plan) == 1
    assert plan[0]["route"] == "hybrid"
    assert plan[0]["question"] == "Who funds X?"


async def test_deep_research_full_flow(monkeypatch):
    monkeypatch.setattr(orch, "generate_json", _plan(
        {"question": "Who authored P?", "route": "graph", "why": "relationship"},
        {"question": "What does P find?", "route": "vector", "why": "content"},
    ))

    answers = {
        "Who authored P?": {
            "answer": "Alice authored P.",
            "graph_records": [{"author": "Alice"}],
            "vector_chunks": [], "conflicts": [{"source": "Alice", "target": "Bob"}],
            "key_entities": [{"name": "Alice", "type": "Person"}],
        },
        "What does P find?": {
            "answer": "P finds Y.",
            "graph_records": [], "vector_chunks": [{"text": "Y"}],
            "conflicts": [], "key_entities": [{"name": "P", "type": "Paper"}],
        },
    }

    async def fake_answer(question, workspace_id, *, force_route=None):
        # Each sub-agent must be pinned to its planned route.
        assert force_route in ("graph", "vector")
        return answers[question]
    monkeypatch.setattr(orch, "answer_question", fake_answer)

    async def fake_synth(prompt):
        return "Alice authored P, which finds Y."
    monkeypatch.setattr(orch, "generate_text", fake_synth)

    async def fake_judge(answer, results):
        return [{"claim": "Alice authored P", "supported": True},
                {"claim": "P finds Y", "supported": True},
                {"claim": "P won an award", "supported": False}]
    monkeypatch.setattr(orch, "judge_faithfulness", fake_judge)

    events = []
    async def on_event(name, payload):
        events.append((name, payload))

    result = await orch.deep_research("Tell me about P", "ws1", on_event=on_event)

    assert result["type"] == "deep_research"
    assert result["answer"] == "Alice authored P, which finds Y."
    assert len(result["subquestions"]) == 2
    assert result["trust"]["score"] == round(2 / 3, 3)
    assert result["trust"]["unsupported_claims"] == ["P won an award"]
    # Conflicts surfaced from the graph sub-agent.
    assert {"source": "Alice", "target": "Bob"} in result["conflicts"]
    # Entities de-duped across sub-agents.
    assert {e["name"] for e in result["key_entities"]} == {"Alice", "P"}

    # The SSE route depends on these event names being emitted in order.
    names = [n for n, _ in events]
    assert names[0] == "status"          # planning
    assert "plan" in names
    assert names.count("subagent") == 4  # running + done per sub-agent
    assert "trust" in names
