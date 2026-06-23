#!/usr/bin/env python3
"""
Phase 4 integration — runs the REAL ingestion pipeline with USE_SHARDING=true and
confirms documents are written across the 3 Neo4j shards (not just one), while
ChromaDB and the source status behave exactly as in the single-node path.

    python scripts/sharded_ingest_test.py

Requires shards on bolt 7687/7688/7689 and GEMINI_API_KEY.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Must be set BEFORE the pipeline modules read it.
os.environ["USE_SHARDING"] = "true"

import asyncio
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select, delete as sa_delete

from backend.db.postgres import AsyncSessionLocal
from backend.db.models import Source, IngestionJob
import backend.db.chroma as chroma
from backend.db.shard_router import ShardRouter
import backend.ingestion.jobs as jobs
from backend.ingestion.jobs import run_ingestion_job, _shutdown_async_resources

WS = "shard_ingest_ws"
_failures: list[str] = []


def check(cond, label):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        _failures.append(label)


_orig_fetch = jobs.fetch_documents_for_source


async def _bounded_fetch(source):
    return (await _orig_fetch(source))[:3]


jobs.fetch_documents_for_source = _bounded_fetch


def run_async(coro):
    async def _wrap():
        try:
            return await coro
        finally:
            await _shutdown_async_resources()
    return asyncio.run(_wrap())


async def _create(stype, url):
    sid = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        db.add(Source(id=sid, workspace_id=WS, type=stype, url=url,
                      status="pending", created_at=datetime.now(timezone.utc)))
        await db.commit()
    return sid


async def _status(sid):
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Source.status).where(Source.id == sid))
        row = r.first()
        return row[0] if row else None


async def _papers_per_shard():
    router = ShardRouter()
    try:
        async def _c(d):
            async with d.session() as s:
                r = await s.run(
                    "MATCH (n:Paper {workspace_id:$ws}) WHERE coalesce(n.is_stub,false)=false "
                    "RETURN count(n) AS c", ws=WS)
                return (await r.single())["c"]
        return [await _c(d) for d in router._drivers]
    finally:
        await router.close()


async def _cleanup():
    async with AsyncSessionLocal() as db:
        sids = (await db.execute(select(Source.id).where(Source.workspace_id == WS))).scalars().all()
        for sid in sids:
            await db.execute(sa_delete(IngestionJob).where(IngestionJob.source_id == sid))
        await db.execute(sa_delete(Source).where(Source.workspace_id == WS))
        await db.commit()
    router = ShardRouter()
    try:
        for d in router._drivers:
            async with d.session() as s:
                await s.run("MATCH (n {workspace_id:$ws}) DETACH DELETE n", ws=WS)
    finally:
        await router.close()
    try:
        chroma._get_client().delete_collection(f"workspace_{WS}_chunks")
    except Exception:
        pass


def main() -> int:
    print("USE_SHARDING =", os.environ["USE_SHARDING"])
    run_async(_cleanup())

    for stype, url in [
        ("web_url", "https://en.wikipedia.org/wiki/Neo4j"),
        ("arxiv_feed", "cs.AI"),  # category -> several papers, spread by hash
    ]:
        print(f"\n-- ingest {stype} ({url}) under sharding --")
        sid = run_async(_create(stype, url))
        run_ingestion_job(sid)
        check(run_async(_status(sid)) == "success", f"{stype}: status success")

    per_shard = run_async(_papers_per_shard())
    total = sum(per_shard)
    chunks = run_async(chroma.get_chunk_count(WS))
    print(f"\n  Paper nodes per shard: {per_shard}  (total={total})")
    print(f"  Chroma chunks: {chunks}")
    check(total > 0, "papers written to the sharded graph")
    check(chunks > 0, "chunks written to ChromaDB")
    check(sum(1 for c in per_shard if c > 0) >= 2,
          "papers distributed across at least 2 shards (real sharding)")

    run_async(_cleanup())

    print("\n" + "=" * 54)
    if _failures:
        print(f"RESULT: {len(_failures)} CHECK(S) FAILED")
        for f in _failures:
            print("  -", f)
        return 1
    print("RESULT: ALL SHARDED-INGEST CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
