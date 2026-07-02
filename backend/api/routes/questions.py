import uuid
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from backend.db.postgres import get_async_db
from backend.db.models import Report
from backend.db import conversations as conv_store
from backend.models.schemas import QuestionRequest, QuestionResponse, ReportSummary
from backend.core.qa_pipeline import answer_question
from backend.core.router import classify_question
from backend.core.graph_retriever import run_graph_query, UnsafeQueryError
from backend.core.vector_retriever import run_vector_query
from backend.core.synthesizer import synthesize_answer
from backend.core import conversation as conv
from backend.core.resilience import CircuitBreakerError
from backend.core.ratelimit import limiter, QUESTION_LIMIT
from backend.core.trust import trust_from_claims, unavailable_trust
from backend.eval.judge import judge_faithfulness
import asyncio

router = APIRouter()


@router.post("/question", response_model=QuestionResponse)
@limiter.limit(QUESTION_LIMIT)
async def ask_question(
    request: Request, req: QuestionRequest, db: AsyncSession = Depends(get_async_db)
):
    # Load prior context when this is a follow-up turn in an existing thread.
    ctx = (
        await conv_store.load_thread_context(db, req.conversation_id)
        if req.conversation_id
        else {"conversation": None, "summary": None, "turns": [], "next_index": 0}
    )

    result = await answer_question(
        req.question, req.workspace_id, history=ctx["turns"], summary=ctx["summary"]
    )

    # Resolve (or open) the conversation this turn belongs to.
    conversation = ctx["conversation"]
    if conversation is None:
        conversation = await conv_store.create_conversation(db, req.workspace_id, req.question)
    turn_index = ctx["next_index"]

    count_result = await db.execute(
        select(func.count(Report.id)).where(
            Report.workspace_id == req.workspace_id,
            Report.question == req.question,
        )
    )
    version = (count_result.scalar() or 0) + 1

    report = Report(
        id=str(uuid.uuid4()),
        workspace_id=req.workspace_id,
        question=req.question,
        answer=result["answer"],
        retrieval_type=result["type"],
        reasoning=result["reasoning"],
        sources_used={
            "cypher": result["cypher"],
            "graph_records": result["graph_records"],
            "vector_chunks": result["vector_chunks"],
            "key_entities": result.get("key_entities", []),
            "insights": result.get("insights", []),
            "conflicts": result.get("conflicts", []),
            "trust": result.get("trust", unavailable_trust()),
        },
        version=version,
        created_at=datetime.now(timezone.utc),
        conversation_id=conversation.id,
        turn_index=turn_index,
        standalone_question=result.get("standalone_question"),
    )
    db.add(report)
    await conv_store.touch_and_maybe_summarize(db, conversation, turn_index)
    await db.commit()
    await db.refresh(report)

    return QuestionResponse(
        id=report.id,
        question=report.question,
        answer=report.answer,
        retrieval_type=report.retrieval_type,
        reasoning=report.reasoning,
        cypher=result["cypher"],
        graph_records=result["graph_records"],
        vector_chunks=result["vector_chunks"],
        key_entities=result.get("key_entities", []),
        insights=result.get("insights", []),
        conflicts=result.get("conflicts", []),
        trust=result.get("trust", unavailable_trust()),
        version=report.version,
        cached=result["cached"],
        created_at=report.created_at,
        conversation_id=conversation.id,
        turn_index=turn_index,
        standalone_question=result.get("standalone_question"),
    )


@router.get("/question/stream")
@limiter.limit(QUESTION_LIMIT)
async def stream_question(
    request: Request,
    question: str = Query(...),
    workspace_id: str = Query(default="arxiv_seed"),
    conversation_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_async_db),
):
    """SSE endpoint that streams progress events then the final answer.

    Events:
      rewrite     → {standalone: "..."}  (only when a follow-up was condensed)
      routing     → {type: "graph"|"vector"|"hybrid"}
      progress    → {status: "..."}
      done        → full QuestionResponse JSON (incl. conversation_id, turn_index)
      error       → {detail: "..."}
    """
    async def generate():
        try:
            # ── Load prior context and condense a follow-up into a standalone ──
            ctx = (
                await conv_store.load_thread_context(db, conversation_id)
                if conversation_id
                else {"conversation": None, "summary": None, "turns": [], "next_index": 0}
            )
            history_block = conv.build_history_block(
                conv.window_turns(ctx["turns"]), ctx["summary"]
            )
            standalone = question
            if history_block:
                yield {"event": "progress", "data": json.dumps({"status": "Resolving follow-up…"})}
                rewrite = await conv.contextualize_question(question, history_block)
                standalone = rewrite["standalone"]
                if rewrite["rewritten"]:
                    yield {"event": "rewrite", "data": json.dumps({"standalone": standalone})}

            # Route the (standalone) question
            yield {"event": "progress", "data": json.dumps({"status": "Analyzing question…"})}
            routing = await classify_question(standalone, workspace_id)
            qtype = routing["type"]
            yield {"event": "routing", "data": json.dumps({"type": qtype})}

            # Retrieve
            graph_records, entity_stats, vector_chunks, cypher = [], [], [], None
            conflicts: list = []
            influence: list = []
            results: dict = {}

            if qtype in ("graph", "hybrid"):
                yield {"event": "progress", "data": json.dumps({"status": "Querying knowledge graph…"})}

            if qtype in ("vector", "hybrid"):
                yield {"event": "progress", "data": json.dumps({"status": "Searching documents…"})}

            async def _graph():
                nonlocal cypher
                try:
                    gr = await run_graph_query(standalone, workspace_id)
                    cypher = gr["cypher"]
                    graph_records[:] = gr["records"]
                    entity_stats[:] = gr.get("entity_stats", [])
                    conflicts[:] = gr.get("conflicts", [])
                    influence[:] = gr.get("influence", [])
                except (UnsafeQueryError, CircuitBreakerError):
                    pass

            async def _vector():
                nonlocal vector_chunks
                try:
                    vr = await run_vector_query(standalone, workspace_id, top_k=8)
                    vector_chunks[:] = vr["chunks"]
                except Exception:
                    pass

            # Same cross-retriever fallback as the POST /question path
            # (qa_pipeline): a misrouted question or an empty retriever result
            # gets a second chance on the other system instead of answering
            # "no information" while the answer sits in the other store.
            if qtype == "hybrid":
                await asyncio.gather(_graph(), _vector())
            elif qtype == "graph":
                await _graph()
                if not graph_records and not entity_stats:
                    await _vector()
            else:
                await _vector()
                if not vector_chunks:
                    await _graph()

            if graph_records:
                results["graph_records"] = graph_records
            if entity_stats:
                results["entity_degree_context"] = entity_stats
            if conflicts:
                results["conflicts"] = conflicts
            if influence:
                results["entity_influence"] = influence
            if vector_chunks:
                results["vector_passages"] = vector_chunks

            yield {"event": "progress", "data": json.dumps({"status": "Synthesizing answer…"})}
            synth_kwargs = {"conversation_context": history_block} if history_block else {}
            synthesis = await synthesize_answer(
                standalone, results, retrieval_type=qtype, **synth_kwargs
            )
            try:
                trust = trust_from_claims(await judge_faithfulness(synthesis["answer"], results))
            except Exception:
                trust = unavailable_trust()

            standalone_question = standalone if standalone.lower() != question.lower() else None
            result = {
                "type": qtype,
                "reasoning": routing["reasoning"],
                "cypher": cypher,
                "graph_records": graph_records,
                "vector_chunks": vector_chunks,
                "conflicts": conflicts,
                "answer": synthesis["answer"],
                "key_entities": synthesis.get("key_entities", []),
                "insights": synthesis.get("insights", []),
                "trust": trust,
                "subquestions": [],
                "cached": False,
            }

            # Resolve (or open) the conversation, then save this turn.
            conversation = ctx["conversation"]
            if conversation is None:
                conversation = await conv_store.create_conversation(db, workspace_id, question)
            turn_index = ctx["next_index"]

            count_result = await db.execute(
                select(func.count(Report.id)).where(
                    Report.workspace_id == workspace_id,
                    Report.question == question,
                )
            )
            version = (count_result.scalar() or 0) + 1
            report = Report(
                id=str(uuid.uuid4()),
                workspace_id=workspace_id,
                question=question,
                answer=result["answer"],
                retrieval_type=result["type"],
                reasoning=result["reasoning"],
                sources_used={
                    "cypher": cypher,
                    "graph_records": graph_records,
                    "vector_chunks": vector_chunks,
                    "key_entities": result.get("key_entities", []),
                    "insights": result.get("insights", []),
                    "conflicts": conflicts,
                    "trust": trust,
                },
                version=version,
                created_at=datetime.now(timezone.utc),
                conversation_id=conversation.id,
                turn_index=turn_index,
                standalone_question=standalone_question,
            )
            db.add(report)
            await conv_store.touch_and_maybe_summarize(db, conversation, turn_index)
            await db.commit()
            await db.refresh(report)

            final = {
                **result,
                "retrieval_type": result["type"],
                "id": report.id,
                "question": question,
                "version": version,
                "created_at": report.created_at.isoformat(),
                "conversation_id": conversation.id,
                "turn_index": turn_index,
                "standalone_question": standalone_question,
            }
            yield {"event": "done", "data": json.dumps(final, default=str)}

        except Exception as exc:
            yield {"event": "error", "data": json.dumps({"detail": str(exc)})}

    return EventSourceResponse(generate())


@router.get("/reports", response_model=list[ReportSummary])
async def list_reports(
    workspace_id: str = Query(default="arxiv_seed"),
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(
        select(Report)
        .where(Report.workspace_id == workspace_id)
        .order_by(Report.created_at.desc())
        .limit(50)
    )
    return result.scalars().all()


@router.get("/reports/{report_id}", response_model=QuestionResponse)
async def get_report(report_id: str, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(404, "Report not found")
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


@router.delete("/reports/{report_id}", status_code=204)
async def delete_report(report_id: str, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(404, "Report not found")
    await db.delete(report)
    await db.commit()
