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

from sqlalchemy import select, update, delete as sql_delete

from backend.db.postgres import AsyncSessionLocal, async_engine
from backend.db.models import Source, IngestionJob
from backend.db.redis import (
    get_checkpoint, set_checkpoint, clear_checkpoint,
    invalidate_workspace_caches, close_async_client,
)
from backend.db import neo4j as neo4j_db
from backend.db import shard_router
from backend.db.queue import get_dlq
from backend.ingestion.dispatcher import fetch_documents_for_source
from backend.ingestion.worker import process_document
from backend.ingestion.entity_resolver import EntityResolver
from backend.core.chroma_backup import trigger_backup_debounced

_CONCURRENCY = 5     # max parallel documents per source
_MAX_RETRIES = 3


def run_ingestion_job(source_id: str, force: bool = False) -> None:
    """Synchronous RQ entry point. Wraps async work with asyncio.run().

    force=True re-extracts and re-embeds documents that were already processed
    (used by the re-ingest endpoints to refresh sources after a pipeline change).
    """
    asyncio.run(_run_and_cleanup(source_id, force=force))


async def _run_and_cleanup(source_id: str, force: bool = False) -> None:
    """Run one job, then ALWAYS tear down every module-global async pool.

    The RQ SimpleWorker (Windows: no os.fork) runs each job in the same process
    via a fresh asyncio.run(), so each job gets a brand-new event loop. The
    SQLAlchemy async engine, Neo4j async driver, and redis.asyncio client are
    module-global singletons that bind their connection pools to the loop that
    first created them. If they are not disposed before that loop closes, the
    NEXT job's loop inherits the stale pools and dies with
    "RuntimeError: Event loop is closed" (often surfacing only at the first DB
    call, or — because Postgres pool_pre_ping can transparently recover — only
    at the later Redis flush, leaving source.status stuck at 'running').

    Disposing in a finally here guarantees teardown even when the job raises.
    """
    try:
        await _run_async(source_id, force=force)
    finally:
        await _shutdown_async_resources()


async def _shutdown_async_resources() -> None:
    """Dispose every module-global async pool the job may have created.

    Each disposal is independently guarded so one failing pool can't prevent the
    others from being released.
    """
    try:
        await async_engine.dispose()
    except Exception:
        pass
    try:
        await neo4j_db.close_async_driver()
    except Exception:
        pass
    try:
        await shard_router.close_router()
    except Exception:
        pass
    try:
        await close_async_client()
    except Exception:
        pass


async def _fail_source(source_id: str, error: str) -> None:
    """Force a source to a terminal 'error' state with its own short-lived session.

    Used from the outer exception handler, where the primary session may already
    be poisoned by the error that got us here.
    """
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Source)
                .where(Source.id == source_id)
                .values(
                    status="error",
                    last_error=(error or "")[:500],
                    error_count=(Source.error_count + 1),
                )
            )
            await db.commit()
    except Exception:
        pass  # last-resort; the startup recovery in main.py is the final backstop


async def _run_async(source_id: str, force: bool = False) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Source).where(Source.id == source_id))
        source = result.scalar_one_or_none()
        if not source:
            return

        workspace_id = source.workspace_id
        source.status = "running"
        # Reset this source's ingest log so the per-source job counts (and the
        # "N failed" badge in the UI) reflect only the current run. Job rows are
        # never otherwise cleared, so a single transient failure would linger as
        # an error forever — even after a clean re-ingest. The real graph/vector
        # data is idempotent (MERGE/upsert) and lives elsewhere, so wiping the
        # per-run bookkeeping loses nothing.
        await db.execute(sql_delete(IngestionJob).where(IngestionJob.source_id == source_id))
        source.error_count = 0
        await db.commit()

        try:
            documents = await fetch_documents_for_source(source)
        except Exception as exc:
            source.status = "error"
            source.error_count = (source.error_count or 0) + 1
            source.last_error = str(exc)[:500]
            await db.commit()
            return

        # A fetch that yields zero documents is a dead-end: the source would be
        # marked 'success' with nothing ingested, so it shows a green "Ready"
        # badge yet every question returns "no information" (observed symptom #4).
        # Surface it as an error instead of that silent black hole.
        if not documents:
            source.status = "error"
            source.error_count = (source.error_count or 0) + 1
            source.last_error = (
                "Fetched 0 documents — the feed/URL may be empty, blocked, or wrong."
            )
            await db.commit()
            return

        # Resume from checkpoint: skip documents already processed.
        # On a forced re-ingest we want every document reprocessed, so ignore it.
        checkpoint = None if force else await get_checkpoint(source_id)
        skip_until = checkpoint
        filtered = []
        for doc in documents:
            if skip_until:
                if doc.get("url") == skip_until:
                    skip_until = None  # found checkpoint, start including from next
                continue
            filtered.append(doc)

        # Everything past this point must leave source.status in a terminal state
        # (success / error) no matter what raises — a stale-loop RuntimeError, a
        # Redis flush failure, a cache-invalidation error, etc. Otherwise the
        # source is stranded at 'running' forever (observed symptom #1).
        try:
            resolver = EntityResolver()
            await resolver.load_from_redis(workspace_id)

            sem = asyncio.Semaphore(_CONCURRENCY)
            outcomes: list[bool] = []

            async def _process_one(doc: dict) -> bool:
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
                        await process_document(doc, workspace_id, resolver, force=force, source_id=source_id)
                        status, error, ok = "success", None, True
                        await set_checkpoint(source_id, doc.get("url", ""))
                    except Exception as exc:
                        status, error, ok = "failed", str(exc)[:500], False
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
                    return ok

            results = await asyncio.gather(
                *[_process_one(doc) for doc in filtered], return_exceptions=True
            )
            # A result that is an Exception means _process_one itself blew up
            # (not a per-document failure, which it catches internally) — count
            # it as a failed document so the source status reflects reality.
            outcomes = [r is True for r in results]

            # Best-effort post-processing — must not strand the source at running.
            try:
                await resolver.flush_to_redis(workspace_id)
                await clear_checkpoint(source_id)
                await invalidate_workspace_caches(workspace_id)
            except Exception:
                pass

            total = len(filtered)
            succeeded = sum(outcomes)
            source.last_fetched = datetime.now(timezone.utc)
            if total > 0 and succeeded == 0:
                # Every document failed — calling this 'success' is what made a
                # green "Ready" source answer "no information" (symptom #3/#4).
                source.status = "error"
                source.error_count = (source.error_count or 0) + 1
                source.last_error = f"All {total} document(s) failed to ingest."
            else:
                source.status = "success"
                source.last_error = None
            await db.commit()

            if source.status == "success":
                try:
                    trigger_backup_debounced()
                except Exception:
                    pass
        except Exception as exc:
            await _fail_source(source_id, str(exc))
            raise


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
