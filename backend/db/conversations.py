"""Conversation persistence helpers shared by the question endpoints.

A conversation's turns are `Report` rows that share a `conversation_id`. These
helpers load the bounded context for a follow-up (recent window + rolling
summary), create the parent row, and fold turns that age out of the window into
the summary. They take an `AsyncSession` and never commit — the calling route
owns the transaction boundary.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core import conversation as conv
from backend.db.models import Conversation, Report


async def load_thread_context(db: AsyncSession, conversation_id: str) -> dict:
    """Load the context needed to answer the next turn of a conversation.

    Returns ``{conversation, summary, turns, next_index}`` where `turns` is the
    most recent window (oldest→newest) ``{question, answer}`` and `next_index`
    is the 0-based index the new turn will take. A missing/unknown id yields an
    empty context so the caller simply treats it as a fresh single-shot question.
    """
    convo = (
        await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    ).scalar_one_or_none()
    if convo is None:
        return {"conversation": None, "summary": None, "turns": [], "next_index": 0}

    total = (
        await db.execute(
            select(func.count(Report.id)).where(Report.conversation_id == conversation_id)
        )
    ).scalar() or 0

    rows = (
        await db.execute(
            select(Report.question, Report.answer)
            .where(Report.conversation_id == conversation_id)
            .order_by(Report.turn_index.desc())
            .limit(conv.CONV_WINDOW_TURNS)
        )
    ).all()
    turns = [{"question": q, "answer": a} for q, a in reversed(rows)]

    return {"conversation": convo, "summary": convo.summary, "turns": turns, "next_index": total}


async def create_conversation(db: AsyncSession, workspace_id: str, title: str) -> Conversation:
    """Create the parent row for a new thread. Title is derived from turn 1."""
    now = datetime.now(timezone.utc)
    convo = Conversation(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        title=(title or "Untitled").strip()[:200],
        created_at=now,
        updated_at=now,
    )
    db.add(convo)
    await db.flush()  # assign the id without committing the caller's transaction
    return convo


async def touch_and_maybe_summarize(
    db: AsyncSession, conversation: Conversation, new_turn_index: int
) -> None:
    """Bump updated_at and fold the turn that just left the window into the summary.

    With a window of W, adding the turn at index `new_turn_index` pushes the turn
    at index `new_turn_index - W` out of the verbatim window. We summarize only
    that single aged-out turn, so this costs one cheap LLM call per turn *beyond*
    the window — not per turn.
    """
    conversation.updated_at = datetime.now(timezone.utc)

    aged_index = new_turn_index - conv.CONV_WINDOW_TURNS
    if aged_index < 0:
        return

    aged = (
        await db.execute(
            select(Report.question, Report.answer).where(
                Report.conversation_id == conversation.id,
                Report.turn_index == aged_index,
            )
        )
    ).first()
    if aged is None:
        return

    conversation.summary = await conv.update_rolling_summary(
        conversation.summary, {"question": aged[0], "answer": aged[1]}
    )
