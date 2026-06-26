"""Conversation context: turn a thread of prior turns into bounded history.

This module owns the *memory* side of multi-turn conversations. It assembles a
compact, token-budgeted history block from a conversation's recent turns plus a
rolling summary of older ones — the hybrid window+summary strategy production
chatbots converge on. The history block it produces is consumed by the
contextualizer (to rewrite follow-ups into standalone questions) and by the
synthesizer (so prose can reference earlier turns).

Everything in this file is pure and LLM-free; the LLM calls (rewrite, summary)
live alongside it but are split out so this part stays trivially testable.
"""
import os

from backend.core.llm_client import generate_json

# Recent turns kept verbatim in the window. Recent turns carry the most
# coreference weight ("his", "that paper"), so they stay in full.
CONV_WINDOW_TURNS = int(os.environ.get("CONV_WINDOW_TURNS", 6))
# Hard cap on the assembled history block — the final backstop on token cost,
# independent of how the window/summary split lands.
CONV_CONTEXT_CHARS = int(os.environ.get("CONV_CONTEXT_CHARS", 6000))
# Each turn's answer is trimmed to this many chars inside the history; the full
# answer is never needed for coreference, just the gist.
CONV_ANSWER_CHARS = int(os.environ.get("CONV_ANSWER_CHARS", 600))


def trim_answer(answer: str, limit: int = CONV_ANSWER_CHARS) -> str:
    """Collapse a markdown answer to a short single-paragraph gist for history.

    The history only needs enough of each answer to resolve references in the
    next question — not the full prose, tables, or citations. We strip the
    heaviest markdown noise and truncate on a word boundary.
    """
    if not answer:
        return ""
    text = " ".join(answer.split())  # collapse whitespace/newlines
    if len(text) <= limit:
        return text
    cut = text[:limit]
    # back up to the last space so we don't slice a word in half
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip() + "…"


def build_history_block(
    recent_turns: list[dict],
    summary: str | None = None,
    *,
    max_chars: int = CONV_CONTEXT_CHARS,
) -> str:
    """Assemble a bounded history block from recent turns + a rolling summary.

    `recent_turns` is oldest→newest, each ``{"question", "answer"}``. `summary`
    is the rolling summary of turns that already aged out of the window. The
    result is capped at `max_chars` by dropping the *oldest* verbatim turns
    first (the summary header and newest turns are the most valuable, so they
    survive). Returns "" when there is nothing to include — the caller treats an
    empty block as "no history, skip the rewrite".
    """
    summary = (summary or "").strip()
    turns = [t for t in recent_turns if (t.get("question") or "").strip()]

    def assemble(turn_subset: list[dict]) -> str:
        parts: list[str] = []
        if summary:
            parts.append("[Earlier context summary]\n" + summary)
        if turn_subset:
            lines: list[str] = []
            for t in turn_subset:
                lines.append(f"Q: {t['question'].strip()}")
                ans = trim_answer(t.get("answer") or "")
                if ans:
                    lines.append(f"A: {ans}")
            parts.append("[Recent turns]\n" + "\n".join(lines))
        return "\n\n".join(parts)

    block = assemble(turns)
    # Drop oldest turns one at a time until the block fits the budget. The
    # summary alone could still exceed it (rare) — hard-truncate as a last resort.
    while len(block) > max_chars and turns:
        turns = turns[1:]
        block = assemble(turns)
    if len(block) > max_chars:
        block = block[:max_chars].rstrip() + "…"
    return block


def window_turns(turns: list[dict], window: int = CONV_WINDOW_TURNS) -> list[dict]:
    """The most recent `window` turns, oldest→newest, kept verbatim."""
    return turns[-window:] if window > 0 else []


# ── Query rewriting (question condensation) ────────────────────────────────────

_CONTEXTUALIZE_PROMPT = """You rewrite a user's follow-up question into a STANDALONE question for a research search engine.

The engine searches a knowledge graph and a document store. It has NO memory of the conversation, so the follow-up must be made fully self-contained: resolve every pronoun ("he", "she", "it", "they"), demonstrative ("that paper", "those authors", "this approach"), and elliptical reference ("what about funding?", "and earlier?") into the explicit entity or topic it refers to, using the conversation history below.

Rules:
- Preserve the user's intent exactly. Do NOT answer the question or add new constraints they didn't ask for.
- Keep it concise — one question, no preamble.
- If the follow-up is ALREADY standalone, or clearly starts a NEW topic unrelated to the history, return it unchanged and set is_followup to false.
- Only set is_followup to true when you actually had to pull context from the history to resolve a reference.

Conversation history:
{history}

Follow-up question: {question}

Return ONLY valid JSON: {{"standalone_question": "...", "is_followup": true|false}}"""

# A rewrite should never balloon into a paragraph — if the model returns
# something implausibly long, we distrust it and fall back to the original.
_MAX_STANDALONE_CHARS = 400


async def contextualize_question(question: str, history_block: str) -> dict:
    """Rewrite a follow-up into a standalone question using the history block.

    Returns ``{"standalone": str, "rewritten": bool, "is_followup": bool}``.

    The LLM call is SKIPPED entirely when there is no history — a new
    conversation's first question is already standalone, so we pay nothing
    (no latency, no tokens) on the common single-shot path. The rewrite only
    fires from the second turn onward.
    """
    question = question.strip()
    if not history_block.strip():
        return {"standalone": question, "rewritten": False, "is_followup": False}

    try:
        data = await generate_json(
            _CONTEXTUALIZE_PROMPT.format(history=history_block, question=question)
        )
    except Exception:
        # Any failure (quota, timeout, bad JSON) must not sink the question —
        # degrade to retrieving on the literal follow-up text.
        return {"standalone": question, "rewritten": False, "is_followup": False}

    standalone = (data.get("standalone_question") or "").strip()
    is_followup = bool(data.get("is_followup"))

    # Guard against a degenerate rewrite: empty, suspiciously long, or unchanged.
    if not standalone or len(standalone) > _MAX_STANDALONE_CHARS:
        return {"standalone": question, "rewritten": False, "is_followup": is_followup}

    rewritten = standalone.lower() != question.lower()
    return {"standalone": standalone, "rewritten": rewritten, "is_followup": is_followup}
