"""
Phase 3 — scheduler.

Pulls sources marked 'pending' from PostgreSQL, expands each into its document
URLs via the existing dispatcher, and loads them into the coordinator's pending
pool as DocRefs. The coordinator then hands them out to workers in batches.

This bridges the existing data model (sources / ingestion_jobs) to the
distributed worker pool without changing the per-document pipeline.
"""
import asyncio

from sqlalchemy import select

from backend.db.postgres import AsyncSessionLocal
from backend.db.models import Source
from backend.ingestion.dispatcher import fetch_documents_for_source
from .registry import WorkerRegistry, DocRef
from .job_tracker import JobTracker


async def pull_pending_once(
    registry: WorkerRegistry, tracker: JobTracker | None = None,
) -> int:
    """Move every 'pending' source's documents into the registry. Marks the
    source 'running' so it isn't picked up twice, and (when a tracker is given)
    pre-creates a 'queued' ingestion_jobs row per document so progress is
    durable and the source rollup can tell in-flight from done. Returns docs
    enqueued."""
    async with AsyncSessionLocal() as db:
        sources = (await db.execute(
            select(Source).where(Source.status == "pending"))).scalars().all()
        enqueued = 0
        scheduled: list[tuple[str, list[str]]] = []
        for src in sources:
            try:
                docs = await fetch_documents_for_source(src)
            except Exception as exc:
                src.status = "error"
                src.last_error = str(exc)[:500]
                continue
            if not docs:
                src.status = "error"
                src.last_error = "Fetched 0 documents."
                continue
            urls = [d.get("url", "") for d in docs]
            await registry.add_documents([
                DocRef(source_id=src.id, document_url=u, workspace_id=src.workspace_id)
                for u in urls
            ])
            src.status = "running"
            scheduled.append((src.id, urls))
            enqueued += len(docs)
        await db.commit()

    # Job rows are created after the source-status commit so a fetch failure
    # above never leaves orphan 'queued' rows for a source we couldn't expand.
    if tracker:
        for sid, urls in scheduled:
            await tracker.create_jobs(sid, urls)
    return enqueued


async def run_scheduler(registry: WorkerRegistry, interval: float = 5.0,
                        stop: asyncio.Event | None = None,
                        tracker: JobTracker | None = None) -> None:
    stop = stop or asyncio.Event()
    while not stop.is_set():
        try:
            n = await pull_pending_once(registry, tracker)
            if n:
                print(f"[scheduler] enqueued {n} document(s) from pending sources")
        except Exception as exc:
            print(f"[scheduler] error: {exc!r}")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
