from fastapi import APIRouter, Query

from backend.core.graph_explorer import get_graph_data
from backend.core import graph_algorithms
from backend.models.schemas import GraphResponse

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
