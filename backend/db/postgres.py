import os
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from dotenv import load_dotenv

load_dotenv()

_sync_url = os.environ["POSTGRES_URL"]


def _build_async_url(sync_url: str) -> tuple[str, dict[str, Any]]:
    """Convert the sync Postgres URL to an asyncpg URL.

    Neon connection strings include sslmode=require for psycopg2. asyncpg does
    not accept sslmode as a query parameter, so strip it from the URL and pass
    the equivalent SSL setting through SQLAlchemy connect_args.
    """
    url = make_url(sync_url)
    drivername = url.drivername
    if drivername in ("postgresql", "postgres"):
        drivername = "postgresql+asyncpg"
    elif drivername.startswith("postgresql+"):
        drivername = "postgresql+asyncpg"

    query = dict(url.query)
    sslmode = query.pop("sslmode", None)
    connect_args: dict[str, Any] = {}
    if sslmode:
        mode = str(sslmode).lower()
        if mode in ("require", "verify-ca", "verify-full"):
            connect_args["ssl"] = True
        elif mode == "disable":
            connect_args["ssl"] = False

    return str(url.set(drivername=drivername, query=query)), connect_args


_async_url, _async_connect_args = _build_async_url(_sync_url)

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
    connect_args=_async_connect_args,
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
