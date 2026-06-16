from datetime import datetime
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
