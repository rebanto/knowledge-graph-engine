"""
Deep Research API — the multi-agent orchestrator exposed over HTTP.

Two entry points over the same `backend.core.orchestrator.deep_research`:
  POST /research/deep         → run to completion, return the full report.
  GET  /research/deep/stream  → SSE: stream planning/sub-agent/trust events live,
                                then a final `done` frame.

Both persist the result as a Report (retrieval_type="deep_research") so it shows
up in history alongside ordinary questions. This path is entirely separate from
/question — the single-shot pipeline is unchanged.
"""
import uuid
import json
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from backend.db.postgres import get_async_db
from backend.db.models import Report, User
from backend.db import conversations as conv_store
from backend.api.deps import get_current_user, require_readable_workspace
from backend.models.schemas import (
    DeepResearchRequest, DeepResearchResponse,
)
from backend.core.orchestrator import deep_research
from backend.core.ratelimit import limiter, DEEP_RESEARCH_LIMIT

router = APIRouter()


def _sources_payload(result: dict) -> dict:
    """What we persist in Report.sources_used so the report renders later."""
    return {
        "subquestions": result.get("subquestions", []),
        "trust": result.get("trust", {}),
        "key_entities": result.get("key_entities", []),
        "conflicts": result.get("conflicts", []),
        "graph_records": result.get("graph_records", []),
        "vector_chunks": result.get("vector_chunks", []),
    }


async def _persist(
    db: AsyncSession, workspace_id: str, question: str, result: dict, user_id: str
):
    """Save the deep-research run as a one-turn conversation + Report."""
    conversation = await conv_store.create_conversation(db, workspace_id, question, user_id)
    count_result = await db.execute(
        select(func.count(Report.id)).where(
            Report.workspace_id == workspace_id,
            Report.question == question,
            (Report.user_id == user_id) | (Report.user_id.is_(None)),
        )
    )
    version = (count_result.scalar() or 0) + 1
    report = Report(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        user_id=user_id,
        question=question,
        answer=result["answer"],
        retrieval_type="deep_research",
        reasoning="Multi-agent deep research: plan → sub-agents → synthesize → verify.",
        sources_used=_sources_payload(result),
        version=version,
        created_at=datetime.now(timezone.utc),
        conversation_id=conversation.id,
        turn_index=0,
    )
    db.add(report)
    await conv_store.touch_and_maybe_summarize(db, conversation, 0)
    await db.commit()
    await db.refresh(report)
    return report, conversation, version


@router.post("/research/deep", response_model=DeepResearchResponse)
@limiter.limit(DEEP_RESEARCH_LIMIT)
async def run_deep_research(
    request: Request,
    req: DeepResearchRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    await require_readable_workspace(db, req.workspace_id, user)
    result = await deep_research(req.question, req.workspace_id)
    report, conversation, version = await _persist(
        db, req.workspace_id, req.question, result, user.id
    )
    return DeepResearchResponse(
        id=report.id,
        question=req.question,
        answer=result["answer"],
        retrieval_type="deep_research",
        subquestions=result["subquestions"],
        key_entities=result["key_entities"],
        conflicts=result["conflicts"],
        trust=result["trust"],
        version=version,
        created_at=report.created_at,
        conversation_id=conversation.id,
    )


@router.get("/research/deep/stream")
@limiter.limit(DEEP_RESEARCH_LIMIT)
async def stream_deep_research(
    request: Request,
    question: str = Query(...),
    workspace_id: str = Query(default="arxiv_seed"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """SSE stream of the deep-research lifecycle.

    Events:
      status   → {phase, message}                  (planning/synthesizing/verifying)
      plan     → {subquestions: [...]}
      subagent → {index, status, question, route, ...}
      trust    → {score, supported, total, unsupported_claims}
      done     → full DeepResearchResponse JSON
      error    → {detail}
    """
    await require_readable_workspace(db, workspace_id, user)

    async def generate():
        # The orchestrator drives progress through an async callback; bridge those
        # callbacks into this generator with a queue so we can `yield` them as SSE.
        queue: asyncio.Queue = asyncio.Queue()
        sentinel = object()

        async def on_event(name: str, payload: dict):
            await queue.put((name, payload))

        async def runner():
            try:
                result = await deep_research(question, workspace_id, on_event=on_event)
                report, conversation, version = await _persist(
                    db, workspace_id, question, result, user.id
                )
                await queue.put(("done", {
                    "id": report.id,
                    "question": question,
                    "answer": result["answer"],
                    "retrieval_type": "deep_research",
                    "subquestions": result["subquestions"],
                    "key_entities": result["key_entities"],
                    "conflicts": result["conflicts"],
                    "trust": result["trust"],
                    "version": version,
                    "created_at": report.created_at.isoformat(),
                    "conversation_id": conversation.id,
                }))
            except Exception as exc:
                await queue.put(("error", {"detail": str(exc)}))
            finally:
                await queue.put(sentinel)

        task = asyncio.create_task(runner())
        try:
            while True:
                item = await queue.get()
                if item is sentinel:
                    break
                name, payload = item
                yield {"event": name, "data": json.dumps(payload, default=str)}
        finally:
            task.cancel()

    return EventSourceResponse(generate())
