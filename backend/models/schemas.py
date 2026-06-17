from datetime import datetime
from typing import Any
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


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    domain: str
    created_at: datetime

    class Config:
        from_attributes = True


class SourceCreate(BaseModel):
    type: str  # arxiv_feed, rss, web_url
    url: str


class SourceResponse(BaseModel):
    id: str
    workspace_id: str
    type: str
    url: str
    status: str
    error_count: int
    last_error: str | None = None
    last_fetched: datetime | None = None
    created_at: datetime

    class Config:
        from_attributes = True
