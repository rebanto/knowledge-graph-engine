from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.db.postgres import Base, engine
from backend.api.routes import questions
from backend.core.llm_client import DailyQuotaExhausted

Base.metadata.create_all(bind=engine)

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


@app.get("/health")
def health():
    return {"status": "ok"}
