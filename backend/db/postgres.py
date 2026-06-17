import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from dotenv import load_dotenv

load_dotenv()

_sync_url = os.environ["POSTGRES_URL"]
# asyncpg requires the postgresql+asyncpg:// scheme
_async_url = _sync_url.replace("postgresql://", "postgresql+asyncpg://", 1)

# ── Sync engine — used by RQ ingestion workers and startup initialization ─────
engine = create_engine(
    _sync_url,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# ── Async engine — used by all FastAPI routes ──────────────────────────────────
async_engine = create_async_engine(
    _async_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=False,
)
AsyncSessionLocal = async_sessionmaker(
    async_engine,
    expire_on_commit=False,
    class_=AsyncSession,
)

Base = declarative_base()


# FastAPI dependency — yields an async session
async def get_async_db():
    async with AsyncSessionLocal() as session:
        yield session


# RQ worker dependency — yields a sync session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
