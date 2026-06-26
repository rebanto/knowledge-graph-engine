"""Unit tests for the conversation context module.

Covers the pure history-assembly logic (window, summary, char budget, answer
trimming) and the LLM-backed contextualizer / rolling summary with the Gemini
call stubbed out — no network, no DB. The contract these pin down:

  * a brand-new conversation (no history) NEVER calls the rewrite LLM, so the
    common single-shot path pays nothing;
  * a degenerate or failing rewrite always degrades to the original question
    rather than sinking it;
  * the assembled history stays within the character budget.
"""
import backend.core.conversation as conv


# ── trim_answer ────────────────────────────────────────────────────────────────

def test_trim_answer_collapses_and_truncates():
    out = conv.trim_answer("word " * 500, limit=50)
    assert len(out) <= 51  # 50 + trailing ellipsis
    assert out.endswith("…")
    assert "\n" not in out


def test_trim_answer_short_passes_through():
    assert conv.trim_answer("a short answer") == "a short answer"


def test_trim_answer_empty():
    assert conv.trim_answer("") == ""


# ── build_history_block ────────────────────────────────────────────────────────

def test_history_block_empty_when_no_input():
    assert conv.build_history_block([], None) == ""


def test_history_block_includes_summary_and_turns():
    block = conv.build_history_block(
        [{"question": "Who is Hinton?", "answer": "A pioneer of deep learning."}],
        summary="Earlier we discussed neural networks.",
    )
    assert "Earlier context summary" in block
    assert "Earlier we discussed neural networks." in block
    assert "Q: Who is Hinton?" in block
    assert "A: A pioneer of deep learning." in block


def test_history_block_respects_char_budget_dropping_oldest():
    turns = [{"question": f"Q{i}", "answer": "x" * 400} for i in range(10)]
    block = conv.build_history_block(turns, None, max_chars=600)
    assert len(block) <= 600
    # The newest turn survives; the oldest is dropped first.
    assert "Q9" in block
    assert "Q0" not in block


# ── window_turns ───────────────────────────────────────────────────────────────

def test_window_turns_keeps_last_k():
    turns = [{"question": str(i), "answer": ""} for i in range(10)]
    win = conv.window_turns(turns, window=3)
    assert [t["question"] for t in win] == ["7", "8", "9"]


# ── contextualize_question ─────────────────────────────────────────────────────

async def test_contextualize_skips_llm_without_history(monkeypatch):
    called = {"n": 0}

    async def boom(prompt):
        called["n"] += 1
        return {}

    monkeypatch.setattr(conv, "generate_json", boom)
    res = await conv.contextualize_question("what about his later work?", "")

    assert called["n"] == 0, "must not call the LLM when there is no history"
    assert res == {"standalone": "what about his later work?", "rewritten": False, "is_followup": False}


async def test_contextualize_rewrites_followup(monkeypatch):
    async def fake(prompt):
        return {"standalone_question": "What is Geoffrey Hinton's later research work?", "is_followup": True}

    monkeypatch.setattr(conv, "generate_json", fake)
    res = await conv.contextualize_question("what about his later work?", "Q: Who is Hinton?\nA: ...")

    assert res["rewritten"] is True
    assert res["is_followup"] is True
    assert "Hinton" in res["standalone"]


async def test_contextualize_falls_back_on_empty_rewrite(monkeypatch):
    async def fake(prompt):
        return {"standalone_question": "", "is_followup": True}

    monkeypatch.setattr(conv, "generate_json", fake)
    res = await conv.contextualize_question("follow up", "Q: prior\nA: prior")

    assert res["standalone"] == "follow up"
    assert res["rewritten"] is False


async def test_contextualize_falls_back_on_exception(monkeypatch):
    async def boom(prompt):
        raise RuntimeError("quota")

    monkeypatch.setattr(conv, "generate_json", boom)
    res = await conv.contextualize_question("follow up", "Q: prior\nA: prior")

    assert res["standalone"] == "follow up"
    assert res["rewritten"] is False


async def test_contextualize_rejects_overlong_rewrite(monkeypatch):
    async def fake(prompt):
        return {"standalone_question": "x" * 1000, "is_followup": True}

    monkeypatch.setattr(conv, "generate_json", fake)
    res = await conv.contextualize_question("follow up", "Q: prior\nA: prior")

    assert res["standalone"] == "follow up"
    assert res["rewritten"] is False


# ── update_rolling_summary ─────────────────────────────────────────────────────

async def test_rolling_summary_folds_turn(monkeypatch):
    async def fake(prompt):
        return {"summary": "We covered Hinton and backprop."}

    monkeypatch.setattr(conv, "generate_json", fake)
    out = await conv.update_rolling_summary("old summary", {"question": "Q", "answer": "A"})
    assert out == "We covered Hinton and backprop."


async def test_rolling_summary_keeps_prev_on_failure(monkeypatch):
    async def boom(prompt):
        raise RuntimeError("down")

    monkeypatch.setattr(conv, "generate_json", boom)
    out = await conv.update_rolling_summary("old summary", {"question": "Q", "answer": "A"})
    assert out == "old summary"


async def test_rolling_summary_ignores_empty_turn(monkeypatch):
    called = {"n": 0}

    async def fake(prompt):
        called["n"] += 1
        return {"summary": "x"}

    monkeypatch.setattr(conv, "generate_json", fake)
    out = await conv.update_rolling_summary("old", {"question": "", "answer": ""})
    assert out == "old"
    assert called["n"] == 0
