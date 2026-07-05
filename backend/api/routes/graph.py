from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, require_readable_workspace
from backend.core.graph_explorer import get_graph_data
from backend.core import graph_algorithms
from backend.db.models import User
from backend.db.postgres import get_async_db
from backend.models.schemas import GraphResponse, Gap, Hypothesis, HypothesisRequest

router = APIRouter()


@router.get("/graph", response_model=GraphResponse)
async def get_graph(
    workspace_id: str = Query(default="arxiv_seed"),
    limit: int = Query(default=150, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    await require_readable_workspace(db, workspace_id, user)
    return await get_graph_data(workspace_id, limit)


@router.get("/graph/influence")
async def get_influence(
    workspace_id: str = Query(default="arxiv_seed"),
    top_n: int = Query(default=25, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Most influential entities by PageRank centrality (cached per workspace)."""
    await require_readable_workspace(db, workspace_id, user)
    return {"influence": await graph_algorithms.workspace_influence(workspace_id, top_n)}


@router.get("/graph/communities")
async def get_communities(
    workspace_id: str = Query(default="arxiv_seed"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Detected entity communities (densely connected clusters), largest first."""
    await require_readable_workspace(db, workspace_id, user)
    return {"communities": await graph_algorithms.workspace_communities(workspace_id)}


@router.get("/graph/gaps", response_model=dict[str, list[Gap]])
async def get_gaps(
    workspace_id: str = Query(default="arxiv_seed"),
    limit: int = Query(default=10, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Plausible missing links ranked by structural link-prediction evidence."""
    await require_readable_workspace(db, workspace_id, user)
    return {"gaps": await graph_algorithms.workspace_research_gaps(workspace_id, limit)}


@router.post("/graph/hypothesis", response_model=Hypothesis)
async def generate_hypothesis(
    body: HypothesisRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Phrase one testable conjecture for a selected graph gap; writes nothing."""
    await require_readable_workspace(db, body.workspace_id, user)
    hypothesis = await graph_algorithms.workspace_gap_hypothesis(
        body.workspace_id,
        body.source,
        body.target,
    )
    if hypothesis is None:
        raise HTTPException(
            status_code=404,
            detail="No structural gap found for that pair.",
        )
    return hypothesis
