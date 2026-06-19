from contextlib import asynccontextmanager
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text, select
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from backend.db.postgres import async_engine, AsyncSessionLocal, Base
from backend.db.models import Workspace
from backend.api.routes import questions, graph, workspaces, sources, system
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

    return JSONResponse(status_code=http_status, content=status)
