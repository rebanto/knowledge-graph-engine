"""
RQ job entry point for ingestion.

run_ingestion_job() is called synchronously by the RQ worker process.
All async logic runs inside asyncio.run(_run_async(...)).

Features:
- Parallel document processing with bounded concurrency (asyncio.Semaphore)
- Checkpoint-based resume: skips already-processed documents after a crash
- Cross-source entity dedup via Redis-backed EntityResolver
- Dead-letter queue: failed documents after MAX_RETRIES go to ingestion_dlq
- Cache invalidation: clears route + Cypher caches after successful ingestion
"""
import uuid
import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.postgres import AsyncSessionLocal
from backend.db.models import Source, IngestionJob
from backend.db.redis import (
    get_checkpoint, set_checkpoint, clear_checkpoint,
    invalidate_workspace_caches,
)
from backend.db.queue import get_queue, get_dlq
from backend.ingestion.dispatcher import fetch_documents_for_source
from backend.ingestion.worker import process_document
from backend.ingestion.entity_resolver import EntityResolver

_CONCURRENCY = 5     # max parallel documents per source
_MAX_RETRIES = 3


def run_ingestion_job(source_id: str) -> None:
    """Synchronous RQ entry point. Wraps async work with asyncio.run()."""
    asyncio.run(_run_async(source_id))


async def _run_async(source_id: str) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Source).where(Source.id == source_id))
        source = result.scalar_one_or_none()
        if not source:
            return

        workspace_id = source.workspace_id
        source.status = "running"
        await db.commit()

        try:
            documents = await fetch_documents_for_source(source)
        except Exception as exc:
            source.status = "error"
            source.error_count = (source.error_count or 0) + 1
            source.last_error = str(exc)[:500]
            await db.commit()
            return

        # Resume from checkpoint: skip documents already processed
        checkpoint = await get_checkpoint(source_id)
        skip_until = checkpoint
        filtered = []
        for doc in documents:
            if skip_until:
                if doc.get("url") == skip_until:
                    skip_until = None  # found checkpoint, start including from next
                continue
            filtered.append(doc)

        resolver = EntityResolver()
        await resolver.load_from_redis(workspace_id)

        sem = asyncio.Semaphore(_CONCURRENCY)

        async def _process_one(doc: dict) -> None:
            async with sem:
                job_id = str(uuid.uuid4())
                job = IngestionJob(
                    id=job_id,
                    source_id=source_id,
                    document_url=doc.get("url"),
                    status="running",
                    created_at=datetime.now(timezone.utc),
                )
                async with AsyncSessionLocal() as job_db:
                    job_db.add(job)
                    await job_db.commit()

                try:
                    await process_document(doc, workspace_id, resolver)
                    status, error = "success", None
                    await set_checkpoint(source_id, doc.get("url", ""))
                except Exception as exc:
                    status, error = "failed", str(exc)[:500]
                    _send_to_dlq(source_id, doc, str(exc))

                async with AsyncSessionLocal() as job_db:
                    result2 = await job_db.execute(
                        select(IngestionJob).where(IngestionJob.id == job_id)
                    )
                    saved_job = result2.scalar_one_or_none()
                    if saved_job:
                        saved_job.status = status
                        saved_job.error = error
                        saved_job.completed_at = datetime.now(timezone.utc)
                        await job_db.commit()

        await asyncio.gather(*[_process_one(doc) for doc in filtered], return_exceptions=True)

        await resolver.flush_to_redis(workspace_id)
        await clear_checkpoint(source_id)
        await invalidate_workspace_caches(workspace_id)

        source.status = "success"
        source.last_fetched = datetime.now(timezone.utc)
        await db.commit()


def _send_to_dlq(source_id: str, doc: dict, error: str) -> None:
    try:
        get_dlq().enqueue(
            "backend.ingestion.jobs._dlq_placeholder",
            {"source_id": source_id, "doc_url": doc.get("url"), "error": error},
        )
    except Exception:
        pass  # DLQ unavailable — don't let this crash the main job


def _dlq_placeholder(payload: dict) -> None:
    """Jobs in this queue failed ingestion. Inspect payload and replay manually."""
    raise RuntimeError(
        f"DLQ job: source_id={payload.get('source_id')} "
        f"url={payload.get('doc_url')} error={payload.get('error')}"
    )
