import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.postgres import get_async_db
from backend.db.models import Workspace, Source, IngestionJob
from backend.db.queue import get_queue
from backend.ingestion.jobs import run_ingestion_job
from backend.models.schemas import WorkspaceCreate, WorkspaceUpdate, WorkspaceResponse, SourceResponse
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


@router.put("/workspaces/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: str, req: WorkspaceUpdate, db: AsyncSession = Depends(get_async_db)
):
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(404, "Workspace not found")
    if req.name is not None:
        workspace.name = req.name
    if req.domain is not None:
        workspace.domain = req.domain
    if req.description is not None:
        workspace.description = req.description
    await db.commit()
    await db.refresh(workspace)
    return workspace


@router.delete("/workspaces/{workspace_id}", status_code=204)
async def delete_workspace(workspace_id: str, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(404, "Workspace not found")
    # Delete related sources and their jobs first
    sources_result = await db.execute(select(Source).where(Source.workspace_id == workspace_id))
    for source in sources_result.scalars().all():
        jobs_result = await db.execute(
            select(IngestionJob).where(IngestionJob.source_id == source.id)
        )
        for job in jobs_result.scalars().all():
            await db.delete(job)
        await db.delete(source)
    # Delete related reports
    from backend.db.models import Report
    reports_result = await db.execute(select(Report).where(Report.workspace_id == workspace_id))
    for report in reports_result.scalars().all():
        await db.delete(report)
    await db.delete(workspace)
    await db.commit()
