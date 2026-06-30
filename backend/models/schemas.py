from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel


class QuestionRequest(BaseModel):
    question: str
    workspace_id: str = "arxiv_seed"
    # When set, this question is a follow-up turn in an existing thread and is
    # answered with that thread's context. Omitted/None starts a new conversation.
    conversation_id: str | None = None


class TrustScore(BaseModel):
    # None when the answer had no checkable factual claims (vacuously grounded).
    score: float | None = None
    supported: int = 0
    total: int = 0
    unsupported_claims: list[str] = []
    claims: list[dict[str, Any]] = []


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
    conflicts: list[dict[str, Any]] = []
    trust: TrustScore = TrustScore()
    version: int
    cached: bool
    created_at: datetime
    # ── Conversation threading ──
    conversation_id: str | None = None
    turn_index: int | None = None
    # The rewritten, self-contained question the retrievers ran on. Null on the
    # first turn or whenever the follow-up was already standalone.
    standalone_question: str | None = None

    class Config:
        from_attributes = True


# ── Deep Research (multi-agent orchestrator) ─────────────────────────────────────

class DeepResearchRequest(BaseModel):
    question: str
    workspace_id: str = "arxiv_seed"


class SubQuestionResult(BaseModel):
    question: str
    route: str
    why: str = ""
    answer: str = ""
    error: str | None = None


class DeepResearchResponse(BaseModel):
    id: str
    question: str
    answer: str
    subquestions: list[SubQuestionResult] = []
    key_entities: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    trust: TrustScore = TrustScore()
    version: int
    created_at: datetime
    conversation_id: str | None = None

    class Config:
        from_attributes = True


# ── Conversations ──────────────────────────────────────────────────────────────

class ConversationSummary(BaseModel):
    id: str
    title: str
    turn_count: int
    retrieval_type: str | None = None  # routing of the most recent turn, for the dot
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConversationDetail(BaseModel):
    id: str
    workspace_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    turns: list[QuestionResponse] = []


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
