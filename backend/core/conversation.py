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
