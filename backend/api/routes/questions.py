import uuid
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from backend.db.postgres import get_async_db
from backend.db.models import Report
from backend.models.schemas import QuestionRequest, QuestionResponse, ReportSummary
from backend.core.qa_pipeline import answer_question
from backend.core.router import classify_question
from backend.core.graph_retriever import run_graph_query, UnsafeQueryError
from backend.core.vector_retriever import run_vector_query
from backend.core.synthesizer import synthesize_answer
from backend.core.resilience import CircuitBreakerError
from backend.db.redis import get_cached_answer, set_cached_answer
import asyncio

router = APIRouter()


@router.post("/question", response_model=QuestionResponse)
async def ask_question(req: QuestionRequest, db: AsyncSession = Depends(get_async_db)):
    result = await answer_question(req.question, req.workspace_id)

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
        },
        version=version,
        created_at=datetime.now(timezone.utc),
    )
    db.add(report)
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
        version=report.version,
        cached=result["cached"],
        created_at=report.created_at,
    )


@router.get("/question/stream")
async def stream_question(
    question: str = Query(...),
    workspace_id: str = Query(default="arxiv_seed"),
    db: AsyncSession = Depends(get_async_db),
):
    """SSE endpoint that streams progress events then the final answer.

    Events:
      routing     → {type: "graph"|"vector"|"hybrid"}
      progress    → {status: "..."}
      done        → full QuestionResponse JSON
      error       → {detail: "..."}
    """
    async def generate():
        try:
            # Check cache first
            cached = await get_cached_answer(workspace_id, question)
            if cached:
                yield {"event": "routing", "data": json.dumps({"type": cached["type"]})}
                yield {"event": "progress", "data": json.dumps({"status": "Served from cache"})}
                yield {"event": "done", "data": json.dumps({**cached, "cached": True})}
                return

            # Route the question
            yield {"event": "progress", "data": json.dumps({"status": "Analyzing question…"})}
            routing = await classify_question(question, workspace_id)
            qtype = routing["type"]
            yield {"event": "routing", "data": json.dumps({"type": qtype})}

            # Retrieve
            graph_records, entity_stats, vector_chunks, cypher = [], [], [], None
            results: dict = {}

            if qtype in ("graph", "hybrid"):
                yield {"event": "progress", "data": json.dumps({"status": "Querying knowledge graph…"})}

            if qtype in ("vector", "hybrid"):
                yield {"event": "progress", "data": json.dumps({"status": "Searching documents…"})}

            async def _graph():
                nonlocal cypher, graph_records, entity_stats
                try:
                    gr = await run_graph_query(question, workspace_id)
                    cypher = gr["cypher"]
                    graph_records[:] = gr["records"]
                    entity_stats[:] = gr.get("entity_stats", [])
                except (UnsafeQueryError, CircuitBreakerError):
                    pass

            async def _vector():
                nonlocal vector_chunks
                try:
                    vr = await run_vector_query(question, workspace_id, top_k=8)
                    vector_chunks[:] = vr["chunks"]
                except Exception:
                    pass

            if qtype == "hybrid":
                await asyncio.gather(_graph(), _vector())
            elif qtype == "graph":
                await _graph()
            else:
                await _vector()

            if graph_records:
                results["graph_records"] = graph_records
            if entity_stats:
                results["entity_degree_context"] = entity_stats
            if vector_chunks:
                results["vector_passages"] = vector_chunks

            yield {"event": "progress", "data": json.dumps({"status": "Synthesizing answer…"})}
            synthesis = await synthesize_answer(question, results, retrieval_type=qtype)

            result = {
                "type": qtype,
                "reasoning": routing["reasoning"],
                "cypher": cypher,
                "graph_records": graph_records,
                "vector_chunks": vector_chunks,
                "answer": synthesis["answer"],
                "key_entities": synthesis.get("key_entities", []),
                "insights": synthesis.get("insights", []),
                "cached": False,
            }

            await set_cached_answer(workspace_id, question, result)

            # Save report
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
                },
                version=version,
                created_at=datetime.now(timezone.utc),
            )
            db.add(report)
            await db.commit()
            await db.refresh(report)

            final = {**result, "id": report.id, "version": version, "created_at": report.created_at.isoformat()}
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
    report = result.scalar_one()
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
        version=report.version,
        cached=False,
        created_at=report.created_at,
    )
