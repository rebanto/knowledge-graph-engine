from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.db.postgres import Base, engine
from backend.api.routes import questions

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Knowledge Graph Research Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(questions.router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}
