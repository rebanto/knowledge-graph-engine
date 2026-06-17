import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.db.postgres import get_db
from backend.db.models import Workspace
from backend.models.schemas import WorkspaceCreate, WorkspaceResponse

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
        created_at=datetime.now(timezone.utc),
    )
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return workspace
