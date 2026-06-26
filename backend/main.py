from contextlib import asynccontextmanager
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text, select, update
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from backend.db.postgres import async_engine, AsyncSessionLocal, Base
from backend.db.models import Workspace, Source
from backend.api.routes import questions, graph, workspaces, sources, system, conversations
from backend.core.llm_client import DailyQuotaExhausted
from backend.core.observability import (
    RequestIDMiddleware, generate_latest, CONTENT_TYPE_LATEST, log,
)


# ── Rate limiter (slowapi) ─────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables, seed default workspace, yield, then close DB pool."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Safe migration: add columns that may not exist in an older DB
        await conn.execute(
            text("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS description TEXT")
        )
        await conn.execute(
            text("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS suggested_questions JSONB")
        )
        # Phase 3: distributed-worker bookkeeping columns on ingestion_jobs.
        for col_ddl in (
            "ADD COLUMN IF NOT EXISTS assigned_worker_id TEXT",
            "ADD COLUMN IF NOT EXISTS batch_id TEXT",
            "ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ",
        ):
            await conn.execute(text(f"ALTER TABLE ingestion_jobs {col_ddl}"))
        # Conversations: thread metadata + the columns that turn a report into a
        # turn. create_all already made the `conversations` table; these guard an
        # older `reports` table that predates threading.
        for col_ddl in (
            "ADD COLUMN IF NOT EXISTS conversation_id TEXT",
            "ADD COLUMN IF NOT EXISTS turn_index INTEGER",
            "ADD COLUMN IF NOT EXISTS standalone_question TEXT",
        ):
            await conn.execute(text(f"ALTER TABLE reports {col_ddl}"))
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_reports_conversation_id "
                 "ON reports (conversation_id)")
        )
        # Safe migration: upgrade TIMESTAMP WITHOUT TIME ZONE → TIMESTAMPTZ
        # Only runs when the column is still the old naive type; no-ops otherwise.
        await conn.execute(text("""
            DO $$
            DECLARE
                col record;
            BEGIN
                FOR col IN
                    SELECT table_name, column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND data_type = 'timestamp without time zone'
                      AND (table_name, column_name) IN (
                        ('workspaces',    'created_at'),
                        ('reports',       'created_at'),
                        ('sources',       'created_at'),
                        ('sources',       'last_fetched'),
                        ('ingestion_jobs','created_at'),
                        ('ingestion_jobs','completed_at')
                      )
                LOOP
                    EXECUTE format(
                        'ALTER TABLE %I ALTER COLUMN %I TYPE TIMESTAMPTZ USING %I AT TIME ZONE ''UTC''',
                        col.table_name, col.column_name, col.column_name
                    );
                END LOOP;
            END $$;
        """))

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Workspace).where(Workspace.id == "arxiv_seed"))
        if not result.scalar_one_or_none():
            db.add(Workspace(id="arxiv_seed", name="ArXiv AI/ML Research", domain="AI/ML research"))
            await db.commit()

        # Crashed-worker recovery: a source can only be 'running' while a worker
        # is actively processing it. If one is still 'running' at startup, the
        # worker that owned it died (kill, restart, stale-loop crash) and no job
        # is in flight — so the source would otherwise be stranded forever.
        # Reset it to 'error' so it shows a real state and can be retried.
        reset = await db.execute(
            update(Source)
            .where(Source.status == "running")
            .values(
                status="error",
                last_error="Ingestion worker stopped before this source finished. Retry to re-ingest.",
            )
        )
        if reset.rowcount:
            log.warning("reset_stranded_sources", count=reset.rowcount)
        await db.commit()

    # Neo4j schema: drop the obsolete global-name uniqueness constraints and
    # create the composite (name|arxiv_id, workspace_id) constraints. This is the
    # multi-tenancy migration — without it, entities created by one workspace are
    # reused (and mis-attributed) by another, so each workspace's graph queries
    # and source deletions miss their own data. Idempotent + safe to re-run.
    # Run in a thread: the Neo4j helper uses the blocking sync driver.
    import asyncio
    from backend.db import neo4j as neo4j_db
    try:
        await asyncio.to_thread(neo4j_db.setup_constraints)
    except Exception as exc:  # never block API startup on a Neo4j hiccup
        log.warning("neo4j_constraint_setup_failed", error=str(exc))

    log.info("startup_complete", env=os.environ.get("ENV", "development"))

    yield

    await async_engine.dispose()
    log.info("shutdown_complete")


app = FastAPI(title="Knowledge Graph Research Engine", lifespan=lifespan)

# ── Middleware ─────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestIDMiddleware)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── Exception handlers ─────────────────────────────────────────────────────────
@app.exception_handler(DailyQuotaExhausted)
async def handle_quota_exhausted(request: Request, exc: DailyQuotaExhausted):
    return JSONResponse(
        status_code=503,
        content={
            "detail": "The LLM provider's daily free-tier quota has been used up. "
            "Try again after the quota resets.",
            "retry_after": 86400,
        },
        headers={"Retry-After": "86400"},
    )


# ── Routes ─────────────────────────────────────────────────────────────────────
app.include_router(questions.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(graph.router, prefix="/api")
app.include_router(workspaces.router, prefix="/api")
app.include_router(sources.router, prefix="/api")
app.include_router(system.router, prefix="/api")


# ── Observability ──────────────────────────────────────────────────────────────
@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics(request: Request) -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health/live", include_in_schema=False)
async def health_live():
    """Liveness: process is up."""
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
async def health_ready():
    """Readiness: all external dependencies reachable."""
    status: dict[str, str] = {}
    http_status = 200

    # Postgres
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        status["postgres"] = "ok"
    except Exception as exc:
        status["postgres"] = f"unreachable: {exc}"
        http_status = 503

    # Redis
    try:
        from backend.db.redis import get_async_client
        await get_async_client().ping()
        status["redis"] = "ok"
    except Exception as exc:
        status["redis"] = f"unreachable: {exc}"
        http_status = 503

    # Neo4j
    try:
        from backend.db.neo4j import get_async_driver
        driver = await get_async_driver()
        async with driver.session() as session:
            await session.run("RETURN 1")
        status["neo4j"] = "ok"
    except Exception as exc:
        status["neo4j"] = f"unreachable: {exc}"
        http_status = 503

    # ChromaDB (vector store) — a hard dependency: if it's down, ingestion can't
    # write and questions can't retrieve document passages.
    try:
        from backend.db.chroma import heartbeat as chroma_heartbeat
        await chroma_heartbeat()
        status["chroma"] = "ok"
    except Exception as exc:
        status["chroma"] = f"unreachable: {exc}"
        http_status = 503

    return JSONResponse(status_code=http_status, content=status)
