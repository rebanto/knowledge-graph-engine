import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db.postgres import get_db
from backend.db.models import Report
from backend.models.schemas import QuestionRequest, QuestionResponse, ReportSummary
from backend.core.qa_pipeline import answer_question

router = APIRouter()


@router.post("/question", response_model=QuestionResponse)
def ask_question(req: QuestionRequest, db: Session = Depends(get_db)):
    result = answer_question(req.question, req.workspace_id)

    version = (
        db.query(func.count(Report.id))
        .filter(Report.workspace_id == req.workspace_id, Report.question == req.question)
        .scalar()
        + 1
    )

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
    db.commit()
    db.refresh(report)

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


@router.get("/reports", response_model=list[ReportSummary])
def list_reports(workspace_id: str = Query(default="arxiv_seed"), db: Session = Depends(get_db)):
    return (
        db.query(Report)
        .filter(Report.workspace_id == workspace_id)
        .order_by(Report.created_at.desc())
        .limit(50)
        .all()
    )


@router.get("/reports/{report_id}", response_model=QuestionResponse)
def get_report(report_id: str, db: Session = Depends(get_db)):
    report = db.query(Report).filter(Report.id == report_id).first()
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
