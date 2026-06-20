from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel


class QuestionRequest(BaseModel):
    question: str
    workspace_id: str = "arxiv_seed"


class QuestionResponse(BaseModel):
    id: str
    question: str
    answer: str
    retrieval_type: str
    reasoning: str
    cypher: str | None = None
    graph_records: list[dict] = []
    vector_chunks: list[dict] = []
    key_entities: list[dict] = []
    insights: list[dict[str, Any]] = []
    version: int
    cached: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ReportSummary(BaseModel):
    id: str
    question: str
    answer: str
    retrieval_type: str
    version: int
    created_at: datetime

    class Config:
        from_attributes = True


class GraphNode(BaseModel):
    name: str
    type: str
    degree: int


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str
    confidence: float | None = None
    conflict: bool = False


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class WorkspaceCreate(BaseModel):
    name: str
    domain: str
    description: str | None = None


class WorkspaceUpdate(BaseModel):
    name: str | None = None
    domain: str | None = None
    description: str | None = None


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    domain: str
    description: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class SourceCreate(BaseModel):
    # type: arxiv_feed | rss | web_url | pdf_upload
    # For arxiv_feed, `url` is NOT necessarily a URL — it accepts:
    #   • category codes  (cs.AI, stat.ML)
    #   • paper IDs       (2401.12345, 2401.12345v2, math/0211159)
    #   • arxiv.org URLs  (https://arxiv.org/abs/2401.12345)
    #   • free-text query (graph neural network interpretability)
    # For pdf_upload, `url` is the server-side file path set by the upload endpoint.
    # For rss / web_url, `url` is a standard HTTP/HTTPS URL.
    type: str
    url: str


class SourceResponse(BaseModel):
    id: str
    workspace_id: str
    type: str
    url: str
    status: str
    error_count: int
    last_error: Optional[str] = None
    last_fetched: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class IngestionJobBrief(BaseModel):
    id: str
    document_url: Optional[str] = None
    status: str
    error: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SourceJobsResponse(BaseModel):
    total: int
    success: int
    failed: int
    running: int
    jobs: list[IngestionJobBrief]
