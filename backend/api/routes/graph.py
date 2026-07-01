from fastapi import APIRouter, HTTPException, Query

from backend.core.graph_explorer import get_graph_data
from backend.core import graph_algorithms
from backend.models.schemas import GraphResponse, Gap, Hypothesis, HypothesisRequest

router = APIRouter()


@router.get("/graph", response_model=GraphResponse)
async def get_graph(
    workspace_id: str = Query(default="arxiv_seed"),
    limit: int = Query(default=150, le=500),
):
    return await get_graph_data(workspace_id, limit)


@router.get("/graph/influence")
async def get_influence(
    workspace_id: str = Query(default="arxiv_seed"),
    top_n: int = Query(default=25, le=100),
):
    """Most influential entities by PageRank centrality (cached per workspace)."""
    return {"influence": await graph_algorithms.workspace_influence(workspace_id, top_n)}


@router.get("/graph/communities")
async def get_communities(workspace_id: str = Query(default="arxiv_seed")):
    """Detected entity communities (densely connected clusters), largest first."""
    return {"communities": await graph_algorithms.workspace_communities(workspace_id)}


@router.get("/graph/gaps", response_model=dict[str, list[Gap]])
async def get_gaps(
    workspace_id: str = Query(default="arxiv_seed"),
    limit: int = Query(default=10, ge=1, le=100),
):
    """Plausible missing links ranked by structural link-prediction evidence."""
    return {"gaps": await graph_algorithms.workspace_research_gaps(workspace_id, limit)}


@router.post("/graph/hypothesis", response_model=Hypothesis)
async def generate_hypothesis(body: HypothesisRequest):
    """Phrase one testable conjecture for a selected graph gap; writes nothing."""
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
