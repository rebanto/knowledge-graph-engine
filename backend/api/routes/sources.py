import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.postgres import get_async_db
from backend.db.models import Source
from backend.db.queue import get_queue
from backend.ingestion.jobs import run_ingestion_job
from backend.models.schemas import SourceCreate, SourceResponse

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
