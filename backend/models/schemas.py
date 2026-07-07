from datetime import datetime
from typing import Any, Literal, Optional
from pydantic import BaseModel, EmailStr, Field

RetrievalRoute = Literal["graph", "vector", "hybrid"]
RetrievalType = Literal["graph", "vector", "hybrid", "deep_research"]


class AuthRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class UserResponse(BaseModel):
    id: str
    email: EmailStr
    created_at: datetime

    class Config:
        from_attributes = True


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
    retrieval_type: RetrievalType
    reasoning: str
    cypher: str | None = None
    graph_records: list[dict] = []
    vector_chunks: list[dict] = []
    key_entities: list[dict] = []
    insights: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    trust: TrustScore = TrustScore()
    subquestions: list["SubQuestionResult"] = []
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
    route: RetrievalRoute
    why: str = ""
    answer: str = ""
    error: str | None = None


class DeepResearchResponse(BaseModel):
    id: str
    question: str
    answer: str
    retrieval_type: Literal["deep_research"] = "deep_research"
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
    retrieval_type: RetrievalType | None = None  # routing of the most recent turn, for the dot
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
    retrieval_type: RetrievalType
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


class GapEntity(BaseModel):
    name: str
    type: str | None = None


class GapEvidence(BaseModel):
    intermediary: GapEntity
    source_relation_types: list[str] = []
    target_relation_types: list[str] = []


class Gap(BaseModel):
    source: GapEntity
    target: GapEntity
    shared_intermediaries: list[GapEvidence] = []
    score: float
    common_neighbor_count: int
    same_community: bool
    interdisciplinary: bool = False
    community_ids: dict[str, int | None] = {}
    why_notable: str | None = None


class HypothesisRequest(BaseModel):
    workspace_id: str = "arxiv_seed"
    source: str
    target: str


class Hypothesis(BaseModel):
    source: GapEntity
    target: GapEntity
    statement: str
    predicted_relationship_type: str
    evidence: list[GapEvidence] = []
    common_neighbor_count: int
    same_community: bool
    interdisciplinary: bool = False
    confidence: str
    reasoning: str
    caveat: str


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
    read_only: bool
    created_at: datetime

    class Config:
        from_attributes = True


class SourceCreate(BaseModel):
    # For arxiv_feed, `url` is NOT necessarily a URL — it accepts:
    #   • category codes  (cs.AI, stat.ML)
    #   • paper IDs       (2401.12345, 2401.12345v2, math/0211159)
    #   • arxiv.org URLs  (https://arxiv.org/abs/2401.12345)
    #   • free-text query (graph neural network interpretability)
    # For rss / web_url, `url` is a standard HTTP/HTTPS URL.
    # pdf_upload is deliberately NOT accepted here: its `url` is a server-side
    # file path, so allowing it through this endpoint would let a client point
    # the ingestion pipeline at ANY file on the server's disk. PDF sources are
    # created only via the /sources/upload endpoint, which owns the path.
    type: Literal["arxiv_feed", "rss", "web_url"]
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
