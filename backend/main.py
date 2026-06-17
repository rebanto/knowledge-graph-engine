from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from backend.db.postgres import Base, engine, SessionLocal
from backend.db.models import Workspace
from backend.api.routes import questions, graph, workspaces, sources
from backend.core.llm_client import DailyQuotaExhausted

Base.metadata.create_all(bind=engine)

# Safe migration: add columns that may not exist in an older DB
with engine.connect() as _conn:
    _conn.execute(text("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS description TEXT"))
    _conn.commit()

with SessionLocal() as db:
    if not db.query(Workspace).filter(Workspace.id == "arxiv_seed").first():
        db.add(Workspace(id="arxiv_seed", name="ArXiv AI/ML Research", domain="AI/ML research"))
        db.commit()

app = FastAPI(title="Knowledge Graph Research Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(DailyQuotaExhausted)
def handle_quota_exhausted(request: Request, exc: DailyQuotaExhausted):
    return JSONResponse(
        status_code=503,
        content={
            "detail": "The LLM provider's daily free-tier quota has been used up. "
            "Try again after the quota resets, or switch to a different model."
        },
    )


app.include_router(questions.router, prefix="/api")
app.include_router(graph.router, prefix="/api")
app.include_router(workspaces.router, prefix="/api")
app.include_router(sources.router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}
