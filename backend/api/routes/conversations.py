"""Conversation endpoints: list threads, load a thread's turns, delete a thread.

Turns are `Report` rows grouped by `conversation_id`. Listing is driven off the
`conversations` table (one row per thread); a thread's detail rehydrates its
ordered turns back into the same `QuestionResponse` shape the ask endpoints
return, so the frontend renders a turn identically whether it just arrived or
was loaded from history.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.postgres import get_async_db
from backend.db.models import Conversation, Report
from backend.models.schemas import (
    ConversationSummary,
    ConversationDetail,
    QuestionResponse,
)
from backend.core.trust import unavailable_trust

router = APIRouter()


def _report_to_response(report: Report) -> QuestionResponse:
    sources = report.sources_used or {}
    return QuestionResponse(
        id=report.id,
        question=report.question,
        answer=report.answer,
        retrieval_type=report.retrieval_type,
        reasoning=report.reasoning or "",
        cypher=sources.get("cypher"),
        graph_records=sources.get("graph_records", []),
        vector_chunks=sources.get("vector_chunks", []),
        key_entities=sources.get("key_entities", []),
        insights=sources.get("insights", []),
        conflicts=sources.get("conflicts", []),
        trust=sources.get("trust", unavailable_trust()),
        subquestions=sources.get("subquestions", []),
        version=report.version,
        cached=False,
        created_at=report.created_at,
        conversation_id=report.conversation_id,
        turn_index=report.turn_index,
        standalone_question=report.standalone_question,
    )


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    workspace_id: str = Query(default="arxiv_seed"),
    db: AsyncSession = Depends(get_async_db),
):
    convos = (
        await db.execute(
            select(Conversation)
            .where(Conversation.workspace_id == workspace_id)
            .order_by(Conversation.updated_at.desc())
            .limit(100)
        )
    ).scalars().all()
    if not convos:
        return []

    ids = [c.id for c in convos]

    # Turn counts per conversation in one grouped query.
    count_rows = (
        await db.execute(
            select(Report.conversation_id, func.count(Report.id))
            .where(Report.conversation_id.in_(ids))
            .group_by(Report.conversation_id)
        )
    ).all()
    counts = {cid: n for cid, n in count_rows}

    # Retrieval type of each thread's most recent turn, for the colored dot.
    latest_rows = (
        await db.execute(
            select(Report.conversation_id, Report.retrieval_type, Report.turn_index)
            .where(Report.conversation_id.in_(ids))
        )
    ).all()
    latest_type: dict[str, tuple[int, str]] = {}
    for cid, rtype, tindex in latest_rows:
        ti = tindex if tindex is not None else 0
        if cid not in latest_type or ti >= latest_type[cid][0]:
            latest_type[cid] = (ti, rtype)

    return [
        ConversationSummary(
            id=c.id,
            title=c.title,
            turn_count=counts.get(c.id, 0),
            retrieval_type=latest_type.get(c.id, (0, None))[1],
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in convos
    ]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str, db: AsyncSession = Depends(get_async_db)):
    convo = (
        await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    ).scalar_one_or_none()
    if convo is None:
        raise HTTPException(404, "Conversation not found")

    turns = (
        await db.execute(
            select(Report)
            .where(Report.conversation_id == conversation_id)
            .order_by(Report.turn_index.asc(), Report.created_at.asc())
        )
    ).scalars().all()

    return ConversationDetail(
        id=convo.id,
        workspace_id=convo.workspace_id,
        title=convo.title,
        created_at=convo.created_at,
        updated_at=convo.updated_at,
        turns=[_report_to_response(t) for t in turns],
    )


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str, db: AsyncSession = Depends(get_async_db)):
    convo = (
        await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    ).scalar_one_or_none()
    if convo is None:
        raise HTTPException(404, "Conversation not found")

    # Delete the thread's turns, then the thread row itself.
    turns = (
        await db.execute(select(Report).where(Report.conversation_id == conversation_id))
    ).scalars().all()
    for t in turns:
        await db.delete(t)
    await db.delete(convo)
    await db.commit()
