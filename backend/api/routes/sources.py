import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.orm import Session

from backend.db.postgres import get_db
from backend.db.models import Source
from backend.db.queue import get_queue
from backend.ingestion.jobs import run_ingestion_job
from backend.models.schemas import SourceCreate, SourceResponse

router = APIRouter()

UPLOAD_DIR = Path(__file__).parent.parent.parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


@router.get("/workspaces/{workspace_id}/sources", response_model=list[SourceResponse])
def list_sources(workspace_id: str, db: Session = Depends(get_db)):
    return (
        db.query(Source)
        .filter(Source.workspace_id == workspace_id)
        .order_by(Source.created_at.desc())
        .all()
    )


@router.post("/workspaces/{workspace_id}/sources", response_model=SourceResponse)
def create_source(workspace_id: str, req: SourceCreate, db: Session = Depends(get_db)):
    source = Source(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        type=req.type,
        url=req.url,
        status="pending",
        created_at=datetime.now(timezone.utc),
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    get_queue().enqueue(run_ingestion_job, source.id, job_timeout=1800)
    return source


@router.post("/workspaces/{workspace_id}/sources/upload", response_model=SourceResponse)
async def upload_pdf_source(
    workspace_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)
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
    db.commit()
    db.refresh(source)

    get_queue().enqueue(run_ingestion_job, source.id, job_timeout=1800)
    return source


@router.delete("/workspaces/{workspace_id}/sources/{source_id}")
def delete_source(workspace_id: str, source_id: str, db: Session = Depends(get_db)):
    db.query(Source).filter(Source.id == source_id, Source.workspace_id == workspace_id).delete()
    db.commit()
    return {"status": "deleted"}
