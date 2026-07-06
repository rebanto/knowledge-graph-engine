"""Production startup bootstraps.

Only env-gated bootstraps live here. Local development keeps the historical
empty public demo workspace unless BOOTSTRAP_DEMO explicitly requests seeding.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import select, delete as sql_delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.observability import log
from backend.db.models import IngestionJob, Source, Workspace
from backend.db.queue import get_queue
from backend.ingestion.jobs import run_ingestion_job

DEMO_WORKSPACE_ID = "arxiv_seed"
DEMO_SOURCE_ID = "arxiv_seed_arxiv_feed"
DEFAULT_ARXIV_QUERY = "cs.AI,cs.LG,cs.CL"


async def bootstrap_demo_if_requested(db: AsyncSession) -> bool:
    """Create and enqueue the public demo workspace once.

    Returns True when the bootstrap created the workspace. Existing databases are
    left alone so restarts do not duplicate sources or enqueue repeated jobs.
    """
    if os.environ.get("BOOTSTRAP_DEMO", "").strip() != DEMO_WORKSPACE_ID:
        return False

    result = await db.execute(select(Workspace).where(Workspace.id == DEMO_WORKSPACE_ID))
    workspace = result.scalar_one_or_none()
    if workspace:
        source_result = await db.execute(select(Source).where(Source.id == DEMO_SOURCE_ID))
        source = source_result.scalar_one_or_none()
        if not source:
            source = Source(
                id=DEMO_SOURCE_ID,
                workspace_id=DEMO_WORKSPACE_ID,
                type="arxiv_feed",
                url=os.environ.get("BOOTSTRAP_ARXIV_QUERY", DEFAULT_ARXIV_QUERY),
                status="pending",
                created_at=datetime.now(timezone.utc),
            )
            db.add(source)
            await db.commit()
        else:
            # The public demo has no owner, so users cannot re-ingest it to clear
            # a lingering per-document failure. Drop any stale 'failed' job rows
            # (and reset the counter) so a successful demo doesn't show a stuck
            # "N failed" badge nobody can act on. Keeps the 'success' rows / doc
            # count intact.
            await db.execute(
                sql_delete(IngestionJob).where(
                    IngestionJob.source_id == source.id,
                    IngestionJob.status == "failed",
                )
            )
            if source.error_count:
                source.error_count = 0
            await db.commit()
        if source.status in ("pending", "error"):
            _enqueue_demo_source(source.id)
        return False

    workspace = Workspace(
        id=DEMO_WORKSPACE_ID,
        name="arxiv_seed",
        domain="AI/ML research",
        description="Public read-only demo workspace seeded from recent AI/ML arXiv papers.",
        owner_user_id=None,
        created_at=datetime.now(timezone.utc),
    )
    source = Source(
        id=DEMO_SOURCE_ID,
        workspace_id=DEMO_WORKSPACE_ID,
        type="arxiv_feed",
        url=os.environ.get("BOOTSTRAP_ARXIV_QUERY", DEFAULT_ARXIV_QUERY),
        status="pending",
        created_at=datetime.now(timezone.utc),
    )
    db.add(workspace)
    db.add(source)
    await db.commit()

    _enqueue_demo_source(source.id)
    return True


def _enqueue_demo_source(source_id: str) -> None:
    # force=True so a recovery re-enqueue (the source was stranded/errored by an
    # interrupted first run) reprocesses cleanly instead of resuming from a stale
    # checkpoint that may not exist in the freshly-fetched paper set. Idempotent:
    # Neo4j MERGE + Chroma upsert mean replays never duplicate.
    try:
        get_queue().enqueue(run_ingestion_job, source_id, force=True, job_timeout=1800)
        log.info("demo_bootstrap_enqueued", workspace_id=DEMO_WORKSPACE_ID, source_id=source_id)
    except Exception as exc:
        log.warning("demo_bootstrap_enqueue_failed", error=str(exc))
