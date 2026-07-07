import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, String, Integer, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from backend.db.postgres import Base


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    domain = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    suggested_questions = Column(JSONB, nullable=True)
    owner_user_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    @hybrid_property
    def read_only(self) -> bool:
        return self.owner_user_id is None


class WorkspaceDismissal(Base):
    __tablename__ = "workspace_dismissals"

    user_id = Column(String, primary_key=True, index=True)
    workspace_id = Column(String, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, nullable=False, unique=True, index=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    is_active = Column(Boolean, nullable=False, default=True)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    token_hash = Column(String, nullable=False, unique=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    replaced_by = Column(String, nullable=True)


class Conversation(Base):
    """A multi-turn thread. Its turns are Report rows sharing this id.

    Reusing reports for the turns keeps the data model small: a report is already
    a (question, answer, sources_used) record, which is exactly one turn. This
    row just holds the thread-level metadata — a derived title and the rolling
    summary of turns that have aged out of the verbatim window.
    """

    __tablename__ = "conversations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id = Column(String, nullable=False, index=True)
    user_id = Column(String, nullable=True, index=True)
    title = Column(Text, nullable=False)
    # Rolling summary of older turns (everything before the verbatim window).
    # NULL until a conversation grows past CONV_WINDOW_TURNS turns.
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )


class Report(Base):
    __tablename__ = "reports"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id = Column(String, nullable=False, index=True)
    user_id = Column(String, nullable=True, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    retrieval_type = Column(String, nullable=False)
    reasoning = Column(Text, nullable=True)
    sources_used = Column(JSONB, nullable=True)
    version = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    # ── Conversation threading (nullable; legacy single-shot reports leave these NULL) ──
    # conversation_id groups a report's turns; turn_index orders them (0-based);
    # standalone_question is the rewritten, self-contained question the retrievers
    # actually ran on (NULL on first turns / when no rewrite was needed).
    conversation_id = Column(String, nullable=True, index=True)
    turn_index = Column(Integer, nullable=True)
    standalone_question = Column(Text, nullable=True)


class Source(Base):
    __tablename__ = "sources"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id = Column(String, nullable=False, index=True)
    type = Column(String, nullable=False)  # arxiv_feed, rss, pdf_upload, web_url
    url = Column(Text, nullable=False)
    status = Column(String, default="pending")  # pending, running, success, error
    error_count = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)
    last_fetched = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id = Column(String, nullable=False, index=True)
    document_url = Column(Text, nullable=True)
    status = Column(String, default="queued")  # queued, running, success, failed
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)
    # Phase 3: distributed worker pool bookkeeping (nullable; unused on RQ path)
    assigned_worker_id = Column(String, nullable=True)
    batch_id = Column(String, nullable=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
