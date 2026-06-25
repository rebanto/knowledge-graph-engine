"""
Phase 3 — Postgres job bookkeeping for the distributed worker pool.

The registry (registry.py) is the coordinator's in-memory source of truth for
*liveness and reassignment*. This module is the durable mirror of that activity
in Postgres: it writes one ``ingestion_jobs`` row per document and rolls the
owning ``sources`` row up to a terminal status when all of its documents finish.
Without it a source enqueued through the coordinator would sit at "running"
forever and the Sources UI could never show progress (the bug this closes).

Idempotency (a document may be processed twice after a worker is reaped and its
batch reassigned) is enforced exactly as CLAUDE.md prescribes:

  • Job rows are keyed by a deterministic id = uuid5(source_id, document_url),
    so a reassigned document updates the *same* row instead of duplicating it.
  • Completion writes are conditional: ``... WHERE status <> 'success'`` so a
    late (reassigned-away) worker can never downgrade an already-succeeded job.

The tracker is injected into the gRPC servicer (default None ⇒ no DB writes), so
the registry and servicer stay unit-testable without a database.
"""
import uuid
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select, update, func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.db.postgres import AsyncSessionLocal
from backend.db.models import IngestionJob, Source

# Fixed namespace so job ids are stable across processes and restarts.
_JOB_NS = uuid.UUID("6f2a9d1e-4c3b-4e7a-9b8c-2d1f0a5e7c43")

_TERMINAL_OK = "success"
_NON_TERMINAL = ("queued", "running")


def job_id_for(source_id: str, document_url: str) -> str:
    """Deterministic ingestion_jobs id for a (source, document) pair."""
    return str(uuid.uuid5(_JOB_NS, f"{source_id}:{document_url}"))


class JobTracker:
    """Durable ingestion_jobs / sources bookkeeping for the coordinator path."""

    async def create_jobs(self, source_id: str, document_urls: Iterable[str]) -> None:
        """Pre-create a 'queued' job row per document when a source is scheduled.

        Up-front creation means the source rollup can tell "still has work to do"
        (queued/running rows exist) from "all done" — without it a rollup firing
        between batches would mark a source 'success' while documents were still
        waiting in the pending pool.
        """
        now = datetime.now(timezone.utc)
        urls = [u for u in document_urls if u]
        if not urls:
            return
        async with AsyncSessionLocal() as db:
            for url in urls:
                stmt = (
                    pg_insert(IngestionJob)
                    .values(
                        id=job_id_for(source_id, url),
                        source_id=source_id,
                        document_url=url,
                        status="queued",
                        created_at=now,
                        completed_at=None,
                        error=None,
                    )
                    # Re-scheduling a source (user marks it pending again) resets
                    # its rows to 'queued' for a fresh run.
                    .on_conflict_do_update(
                        index_elements=[IngestionJob.id],
                        set_={"status": "queued", "completed_at": None, "error": None},
                    )
                )
                await db.execute(stmt)
            await db.commit()

    async def mark_assigned(
        self, docs: list, batch_id: str, worker_id: str,
    ) -> None:
        """Flip a batch's documents to 'running' and record who owns them.

        Conditional on status <> 'success' so a reassigned duplicate can't reopen
        a job another worker already finished.
        """
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            for d in docs:
                await db.execute(
                    update(IngestionJob)
                    .where(
                        IngestionJob.id == job_id_for(d.source_id, d.document_url),
                        IngestionJob.status != _TERMINAL_OK,
                    )
                    .values(
                        status="running",
                        assigned_worker_id=worker_id,
                        batch_id=batch_id,
                        heartbeat_at=now,
                    )
                )
            await db.commit()

    async def touch_heartbeat(self, batch_id: str) -> None:
        """Bump heartbeat_at for a batch's in-flight jobs (cheap liveness trail)."""
        if not batch_id:
            return
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(IngestionJob)
                .where(IngestionJob.batch_id == batch_id, IngestionJob.status == "running")
                .values(heartbeat_at=now)
            )
            await db.commit()

    async def mark_completed(
        self, docs: list, succeeded_urls: list[str], failed_urls: list[str],
    ) -> None:
        """Record per-document outcomes, then roll up each affected source."""
        by_url = {d.document_url: d for d in docs}
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            for url in succeeded_urls:
                d = by_url.get(url)
                if not d:
                    continue
                await db.execute(
                    update(IngestionJob)
                    .where(
                        IngestionJob.id == job_id_for(d.source_id, url),
                        IngestionJob.status != _TERMINAL_OK,
                    )
                    .values(status="success", error=None, completed_at=now)
                )
            for url in failed_urls:
                d = by_url.get(url)
                if not d:
                    continue
                await db.execute(
                    update(IngestionJob)
                    .where(
                        IngestionJob.id == job_id_for(d.source_id, url),
                        IngestionJob.status != _TERMINAL_OK,
                    )
                    .values(status="failed", completed_at=now)
                )
            await db.commit()

        await self.rollup_sources({d.source_id for d in docs})

    async def rollup_sources(self, source_ids: Iterable[str]) -> None:
        """Set a source to its terminal status once none of its jobs are pending.

        success  → at least one document succeeded and nothing is still in flight
        error    → every document failed
        (left running while any queued/running job remains)
        """
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            for sid in source_ids:
                rows = (await db.execute(
                    select(IngestionJob.status, func.count())
                    .where(IngestionJob.source_id == sid)
                    .group_by(IngestionJob.status)
                )).all()
                counts = {status: n for status, n in rows}
                total = sum(counts.values())
                if total == 0:
                    continue
                if any(counts.get(s, 0) > 0 for s in _NON_TERMINAL):
                    continue  # still has work in flight

                succeeded = counts.get("success", 0)
                if succeeded == 0:
                    await db.execute(
                        update(Source)
                        .where(Source.id == sid, Source.status != "error")
                        .values(
                            status="error",
                            last_fetched=now,
                            last_error=f"All {total} document(s) failed to ingest.",
                        )
                    )
                else:
                    await db.execute(
                        update(Source)
                        .where(Source.id == sid, Source.status != "success")
                        .values(status="success", last_fetched=now, last_error=None)
                    )
            await db.commit()
