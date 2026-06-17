import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.db.postgres import get_db
from backend.db.models import Workspace, Source
from backend.db.queue import get_queue
from backend.ingestion.jobs import run_ingestion_job
from backend.models.schemas import WorkspaceCreate, WorkspaceResponse, SourceResponse
from backend.core.source_discovery import suggest_arxiv_categories

router = APIRouter()


@router.get("/workspaces", response_model=list[WorkspaceResponse])
def list_workspaces(db: Session = Depends(get_db)):
    return db.query(Workspace).order_by(Workspace.created_at.asc()).all()


@router.post("/workspaces", response_model=WorkspaceResponse)
def create_workspace(req: WorkspaceCreate, db: Session = Depends(get_db)):
    workspace = Workspace(
        id=str(uuid.uuid4()),
        name=req.name,
        domain=req.domain,
        description=req.description or None,
        created_at=datetime.now(timezone.utc),
    )
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return workspace


@router.post("/workspaces/{workspace_id}/discover", response_model=list[SourceResponse])
def discover_sources(workspace_id: str, db: Session = Depends(get_db)):
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(404, "Workspace not found")
    if not workspace.description:
        raise HTTPException(400, "Set a workspace description before auto-discovering sources")

    categories = suggest_arxiv_categories(workspace.description)
    if not categories:
        raise HTTPException(422, "Could not determine relevant sources from the description")

    created = []
    for cat in categories:
        exists = db.query(Source).filter(
            Source.workspace_id == workspace_id,
            Source.url == cat,
            Source.type == "arxiv_feed",
        ).first()
        if exists:
            continue
        source = Source(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            type="arxiv_feed",
            url=cat,
            status="pending",
            created_at=datetime.now(timezone.utc),
        )
        db.add(source)
        db.commit()
        db.refresh(source)
        get_queue().enqueue(run_ingestion_job, source.id, job_timeout=1800)
        created.append(source)

    return created
