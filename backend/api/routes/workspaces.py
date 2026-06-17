import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.postgres import get_async_db
from backend.db.models import Workspace, Source
from backend.db.queue import get_queue
from backend.ingestion.jobs import run_ingestion_job
from backend.models.schemas import WorkspaceCreate, WorkspaceResponse, SourceResponse
from backend.core.source_discovery import suggest_arxiv_categories

router = APIRouter()


@router.get("/workspaces", response_model=list[WorkspaceResponse])
async def list_workspaces(db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(Workspace).order_by(Workspace.created_at.asc()))
    return result.scalars().all()


@router.post("/workspaces", response_model=WorkspaceResponse)
async def create_workspace(req: WorkspaceCreate, db: AsyncSession = Depends(get_async_db)):
    workspace = Workspace(
        id=str(uuid.uuid4()),
        name=req.name,
        domain=req.domain,
        description=req.description or None,
        created_at=datetime.now(timezone.utc),
    )
    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)
    return workspace


@router.post("/workspaces/{workspace_id}/discover", response_model=list[SourceResponse])
async def discover_sources(workspace_id: str, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(404, "Workspace not found")
    if not workspace.description:
        raise HTTPException(400, "Set a workspace description before auto-discovering sources")

    categories = await suggest_arxiv_categories(workspace.description)
    if not categories:
        raise HTTPException(422, "Could not determine relevant sources from the description")

    created = []
    for cat in categories:
        exists_result = await db.execute(
            select(Source).where(
                Source.workspace_id == workspace_id,
                Source.url == cat,
                Source.type == "arxiv_feed",
            )
        )
        if exists_result.scalar_one_or_none():
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
        await db.commit()
        await db.refresh(source)
        get_queue().enqueue(run_ingestion_job, source.id, job_timeout=1800)
        created.append(source)

    return created
