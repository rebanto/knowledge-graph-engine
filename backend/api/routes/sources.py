import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.postgres import get_async_db
from backend.db.models import Source, IngestionJob
from backend.db.queue import get_queue
from backend.ingestion.jobs import run_ingestion_job
from backend.models.schemas import SourceCreate, SourceResponse, SourceJobsResponse

router = APIRouter()

UPLOAD_DIR = Path(__file__).parent.parent.parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


@router.get("/workspaces/{workspace_id}/sources", response_model=list[SourceResponse])
async def list_sources(workspace_id: str, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(
        select(Source)
        .where(Source.workspace_id == workspace_id)
        .order_by(Source.created_at.desc())
    )
    return result.scalars().all()


@router.post("/workspaces/{workspace_id}/sources", response_model=SourceResponse)
async def create_source(
    workspace_id: str, req: SourceCreate, db: AsyncSession = Depends(get_async_db)
):
    source = Source(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        type=req.type,
        url=req.url,
        status="pending",
        created_at=datetime.now(timezone.utc),
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)

    get_queue().enqueue(run_ingestion_job, source.id, job_timeout=1800)
    return source


@router.post("/workspaces/{workspace_id}/sources/upload", response_model=SourceResponse)
async def upload_pdf_source(
    workspace_id: str, file: UploadFile = File(...), db: AsyncSession = Depends(get_async_db)
):
    dest = UPLOAD_DIR / f"{uuid.uuid4()}_{file.filename}"
    contents = await file.read()
    dest.write_bytes(contents)

    source = Source(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        type="pdf_upload",
        url=str(dest),
        status="pending",
        created_at=datetime.now(timezone.utc),
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)

    get_queue().enqueue(run_ingestion_job, source.id, job_timeout=1800)
    return source


@router.get("/workspaces/{workspace_id}/sources/{source_id}/jobs", response_model=SourceJobsResponse)
async def list_source_jobs(
    workspace_id: str,
    source_id: str,
    limit: int = 50,
    db: AsyncSession = Depends(get_async_db),
):
    source_result = await db.execute(
        select(Source).where(Source.id == source_id, Source.workspace_id == workspace_id)
    )
    if not source_result.scalar_one_or_none():
        raise HTTPException(404, "Source not found")

    counts_result = await db.execute(
        select(IngestionJob.status, func.count(IngestionJob.id))
        .where(IngestionJob.source_id == source_id)
        .group_by(IngestionJob.status)
    )
    counts: dict[str, int] = dict(counts_result.all())

    jobs_result = await db.execute(
        select(IngestionJob)
        .where(IngestionJob.source_id == source_id)
        .order_by(IngestionJob.created_at.desc())
        .limit(limit)
    )
    jobs = jobs_result.scalars().all()

    return {
        "total": sum(counts.values()),
        "success": counts.get("success", 0),
        "failed": counts.get("failed", 0),
        "running": counts.get("running", 0),
        "jobs": jobs,
    }


@router.post("/workspaces/{workspace_id}/sources/{source_id}/retry")
async def retry_source(
    workspace_id: str,
    source_id: str,
    db: AsyncSession = Depends(get_async_db),
):
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.workspace_id == workspace_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(404, "Source not found")

    source.status = "pending"
    source.last_error = None
    await db.commit()
    await db.refresh(source)

    get_queue().enqueue(run_ingestion_job, source.id, job_timeout=1800)
    return {"status": "queued", "source": source}


@router.post("/workspaces/{workspace_id}/sources/{source_id}/reingest")
async def reingest_source(
    workspace_id: str,
    source_id: str,
    db: AsyncSession = Depends(get_async_db),
):
    """Force a full re-ingest of one source.

    Unlike /retry, this re-extracts and re-embeds documents that were already
    processed (force=True bypasses the 'already processed' checkpoint). Use after
    a pipeline change so existing sources pick up the new extraction. Safe to
    replay: Neo4j MERGE + ChromaDB upsert mean no duplicates.
    """
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.workspace_id == workspace_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(404, "Source not found")

    source.status = "pending"
    source.last_error = None
    await db.commit()

    get_queue().enqueue(run_ingestion_job, source.id, force=True, job_timeout=1800)
    return {"status": "queued", "source_id": source.id}


@router.post("/workspaces/{workspace_id}/sources/reingest")
async def reingest_workspace(
    workspace_id: str,
    db: AsyncSession = Depends(get_async_db),
):
    """Force a full re-ingest of every source in the workspace."""
    result = await db.execute(
        select(Source).where(Source.workspace_id == workspace_id)
    )
    sources = result.scalars().all()
    if not sources:
        raise HTTPException(404, "No sources in workspace")

    for source in sources:
        source.status = "pending"
        source.last_error = None
    await db.commit()

    for source in sources:
        get_queue().enqueue(run_ingestion_job, source.id, force=True, job_timeout=1800)

    return {"status": "queued", "count": len(sources), "source_ids": [s.id for s in sources]}


@router.delete("/workspaces/{workspace_id}/sources/{source_id}")
async def delete_source(
    workspace_id: str, source_id: str, db: AsyncSession = Depends(get_async_db)
):
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.workspace_id == workspace_id)
    )
    source = result.scalar_one_or_none()
    if source:
        await db.delete(source)
        await db.commit()
    return {"status": "deleted"}
