from fastapi import APIRouter, Query

from backend.core.graph_explorer import get_graph_data
from backend.models.schemas import GraphResponse

router = APIRouter()


@router.get("/graph", response_model=GraphResponse)
async def get_graph(
    workspace_id: str = Query(default="arxiv_seed"),
    limit: int = Query(default=150, le=500),
):
    return await get_graph_data(workspace_id, limit)
