#!/usr/bin/env python3
"""
End-to-end verification of the full source lifecycle against REAL services
(Postgres, Neo4j, ChromaDB, Redis, Gemini).

Exercises, for every source type (web_url, arxiv_feed, rss, pdf_upload):
  - the real RQ entry point run_ingestion_job() (fetch -> process -> Neo4j +
    Chroma -> terminal status), including the restored per-job async teardown
  - that the source reaches status 'success' and actually wrote chunks + nodes

Then a full lifecycle on a web source:
  add -> query (vector) -> delete (sweeps Chroma + Neo4j + Postgres + checkpoint)
      -> confirm data gone -> re-add -> confirm re-ingest happened.

Running run_ingestion_job() multiple times in one process is itself the
real-pipeline proof of the "Event loop is closed" fix: each call is a fresh
asyncio.run(), exactly like the SimpleWorker.

    python scripts/e2e_source_test.py

Requires the docker-compose services up and GEMINI_API_KEY set.
Uses an isolated workspace 'e2e_test_ws' and cleans up after itself.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select, delete as sa_delete

from backend.db.postgres import AsyncSessionLocal
from backend.db.models import Source, IngestionJob
import backend.db.chroma as chroma
import backend.db.neo4j as neo4j_db
from backend.core.vector_retriever import run_vector_query
import backend.ingestion.jobs as jobs
from backend.ingestion.jobs import run_ingestion_job, _shutdown_async_resources
from backend.api.routes.sources import delete_source

WS = "e2e_test_ws"
UPLOAD_DIR = Path(__file__).parent.parent / "uploads"

# ── Bound fetch to keep the test fast / quota-light (<=2 docs per source) ──────
_orig_fetch = jobs.fetch_documents_for_source


async def _bounded_fetch(source):
    docs = await _orig_fetch(source)
    return docs[:2]


jobs.fetch_documents_for_source = _bounded_fetch

_failures: list[str] = []


def check(cond: bool, label: str) -> bool:
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        _failures.append(label)
    return cond


def run_async(coro):
    """asyncio.run() + dispose pools after, so the harness itself survives the
    one-loop-per-call pattern (same teardown the real job uses)."""
    async def _wrap():
        try:
            return await coro
        finally:
            await _shutdown_async_resources()
    return asyncio.run(_wrap())


# ── A hand-built, text-extractable PDF (no reportlab available) ────────────────

def make_pdf(path: Path, lines: list[str]) -> None:
    stream = "BT /F1 12 Tf 72 740 Td 14 TL\n"
    for line in lines:
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream += f"({safe}) Tj T*\n"
    stream += "ET"
    objects = {
        1: "<< /Type /Catalog /Pages 2 0 R >>",
        2: "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"),
        4: f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        5: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    out = "%PDF-1.4\n"
    offsets = {}
    for n in range(1, 6):
        offsets[n] = len(out.encode("latin-1"))
        out += f"{n} 0 obj\n{objects[n]}\nendobj\n"
    xref_pos = len(out.encode("latin-1"))
    out += "xref\n0 6\n0000000000 65535 f \n"
    for n in range(1, 6):
        out += f"{offsets[n]:010d} 00000 n \n"
    out += f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF"
    path.write_bytes(out.encode("latin-1"))


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _create_source(stype: str, url: str) -> str:
    sid = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        db.add(Source(
            id=sid, workspace_id=WS, type=stype, url=url,
            status="pending", created_at=datetime.now(timezone.utc),
        ))
        await db.commit()
    return sid


async def _source_status(sid: str) -> str | None:
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Source.status).where(Source.id == sid))
        row = r.first()
        return row[0] if row else None


async def _paper_count() -> int:
    driver = await neo4j_db.get_async_driver()
    async with driver.session() as s:
        r = await s.run("MATCH (n:Paper {workspace_id:$ws}) RETURN count(n) AS c", ws=WS)
        return (await r.single())["c"]


async def _chunk_count() -> int:
    return await chroma.get_chunk_count(WS)


async def _cleanup_workspace() -> None:
    # Postgres
    async with AsyncSessionLocal() as db:
        sids = (await db.execute(select(Source.id).where(Source.workspace_id == WS))).scalars().all()
        for sid in sids:
            await db.execute(sa_delete(IngestionJob).where(IngestionJob.source_id == sid))
        await db.execute(sa_delete(Source).where(Source.workspace_id == WS))
        await db.commit()
    # Neo4j
    driver = await neo4j_db.get_async_driver()
    async with driver.session() as s:
        await s.run("MATCH (n {workspace_id:$ws}) DETACH DELETE n", ws=WS)
    # Chroma
    try:
        chroma._get_client().delete_collection(f"workspace_{WS}_chunks")
    except Exception:
        pass


# ── Test stages ────────────────────────────────────────────────────────────────

def stage_each_type():
    print("\n=== STAGE 1: ingest every source type via run_ingestion_job ===")
    pdf_path = UPLOAD_DIR / f"{uuid.uuid4()}_e2e_test.pdf"
    UPLOAD_DIR.mkdir(exist_ok=True)
    make_pdf(pdf_path, [
        "Knowledge Graph Engine Test Document.",
        "The Transformer architecture was introduced by Vaswani and colleagues.",
        "BERT is a language model based on the Transformer encoder.",
        "Attention mechanisms power modern deep learning systems.",
        "This document mentions OpenAI, Google DeepMind, and Stanford University.",
    ])

    cases = [
        ("web_url",    "https://en.wikipedia.org/wiki/Knowledge_graph"),
        ("arxiv_feed", "1706.03762"),  # Attention Is All You Need
        # arxiv's own RSS endpoint is blocked/empty from many networks; a
        # general news feed exercises the same RSS code path with live data.
        ("rss",        "https://feeds.bbci.co.uk/news/rss.xml"),
        ("pdf_upload", str(pdf_path)),
    ]

    for stype, url in cases:
        print(f"\n-- {stype} ({url[:60]}) --")
        chunks_before = run_async(_chunk_count())
        papers_before = run_async(_paper_count())
        sid = run_async(_create_source(stype, url))
        try:
            run_ingestion_job(sid)  # real RQ entry: fresh loop + teardown
        except Exception as exc:
            check(False, f"{stype}: run_ingestion_job raised: {exc!r}")
            continue
        status = run_async(_source_status(sid))
        chunks_after = run_async(_chunk_count())
        papers_after = run_async(_paper_count())
        check(status == "success", f"{stype}: status reached 'success' (got {status!r})")
        check(chunks_after > chunks_before,
              f"{stype}: chunks written ({chunks_before} -> {chunks_after})")
        check(papers_after > papers_before,
              f"{stype}: Paper node(s) written ({papers_before} -> {papers_after})")

    try:
        pdf_path.unlink()
    except Exception:
        pass


def stage_lifecycle():
    print("\n=== STAGE 2: add -> query -> delete -> re-add lifecycle (web) ===")
    url = "https://en.wikipedia.org/wiki/Graph_database"
    sid = run_async(_create_source("web_url", url))
    run_ingestion_job(sid)
    status = run_async(_source_status(sid))
    check(status == "success", f"lifecycle: initial ingest success (got {status!r})")

    # query returns this source's content
    res = run_async(run_vector_query("What is a graph database?", WS, top_k=5))
    hit = any(url in (c.get("source_url") or "") for c in res["chunks"])
    check(len(res["chunks"]) > 0, "lifecycle: vector query returns chunks after ingest")
    check(hit, "lifecycle: returned chunks include the ingested source URL")

    # delete via the real route
    async def _do_delete():
        async with AsyncSessionLocal() as db:
            return await delete_source(WS, sid, db)
    run_async(_do_delete())

    # confirm gone from Chroma + Neo4j
    res2 = run_async(run_vector_query("What is a graph database?", WS, top_k=5))
    still = any(url in (c.get("source_url") or "") for c in res2["chunks"])
    check(not still, "lifecycle: deleted source no longer appears in vector results")

    async def _paper_for_url():
        driver = await neo4j_db.get_async_driver()
        async with driver.session() as s:
            r = await s.run(
                "MATCH (n:Paper {workspace_id:$ws, url:$u}) RETURN count(n) AS c", ws=WS, u=url)
            return (await r.single())["c"]
    check(run_async(_paper_for_url()) == 0, "lifecycle: deleted source's Paper node removed from Neo4j")

    # re-add the SAME url -> must actually re-ingest (not skip)
    sid2 = run_async(_create_source("web_url", url))
    run_ingestion_job(sid2)
    status2 = run_async(_source_status(sid2))
    check(status2 == "success", f"lifecycle: re-add ingest success (got {status2!r})")
    res3 = run_async(run_vector_query("What is a graph database?", WS, top_k=5))
    back = any(url in (c.get("source_url") or "") for c in res3["chunks"])
    check(back, "lifecycle: re-added source is searchable again (re-ingest happened)")
    check(run_async(_paper_for_url()) > 0, "lifecycle: re-added source's Paper node present again")


def main() -> int:
    print("Cleaning any prior test data...")
    run_async(_cleanup_workspace())
    try:
        stage_each_type()
        stage_lifecycle()
    finally:
        print("\nCleaning up test workspace...")
        run_async(_cleanup_workspace())

    print("\n" + "=" * 60)
    if _failures:
        print(f"RESULT: {len(_failures)} CHECK(S) FAILED:")
        for f in _failures:
            print(f"  - {f}")
        return 1
    print("RESULT: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
