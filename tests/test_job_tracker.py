"""Live Postgres integration tests for the coordinator's JobTracker.

Covers the Phase 3 durability layer: per-document ingestion_jobs rows, the
queued→running→success/failed lifecycle, the source rollup to a terminal
status, and the idempotency guarantee that a late (reassigned-away) worker can
never downgrade a job another worker already marked 'success'.

Auto-skips unless Postgres is reachable. Creates a throwaway source + its job
rows and deletes them in teardown, so real data is never touched.
"""
import uuid

import pytest
from sqlalchemy import select, delete

pytestmark = pytest.mark.asyncio


class _Doc:
    """Minimal DocRef stand-in (the tracker only reads .source_id/.document_url)."""
    def __init__(self, source_id: str, document_url: str):
        self.source_id = source_id
        self.document_url = document_url
        self.workspace_id = "test_ws"


@pytest.fixture
async def pg():
    from backend.db.postgres import AsyncSessionLocal, async_engine
    from backend.db.models import Source, IngestionJob
    # pytest-asyncio gives each test its own event loop, but the module-global
    # async engine binds its pool to whichever loop first used it. Drop that
    # stale binding (without touching the now-closed loop) so this test gets a
    # fresh pool on its own loop — otherwise alternate tests fail to connect.
    await async_engine.dispose(close=False)
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(select(Source.id).limit(1))
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Postgres unavailable: {e}")

    sid = f"jt_test_{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        db.add(Source(id=sid, workspace_id="test_ws", type="web_url",
                      url="http://example.test", status="pending"))
        await db.commit()

    yield sid

    async with AsyncSessionLocal() as db:
        await db.execute(delete(IngestionJob).where(IngestionJob.source_id == sid))
        await db.execute(delete(Source).where(Source.id == sid))
        await db.commit()


async def _job_statuses(sid: str) -> dict:
    from backend.db.postgres import AsyncSessionLocal
    from backend.db.models import IngestionJob
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(IngestionJob.document_url, IngestionJob.status)
            .where(IngestionJob.source_id == sid))).all()
    return {url: status for url, status in rows}


async def _source_status(sid: str) -> str:
    from backend.db.postgres import AsyncSessionLocal
    from backend.db.models import Source
    async with AsyncSessionLocal() as db:
        return (await db.execute(
            select(Source.status).where(Source.id == sid))).scalar_one()


async def test_full_lifecycle_rolls_source_up_to_success(pg):
    from backend.coordinator.job_tracker import JobTracker
    sid = pg
    t = JobTracker()
    urls = ["http://example.test/a", "http://example.test/b", "http://example.test/c"]
    docs = [_Doc(sid, u) for u in urls]

    await t.create_jobs(sid, urls)
    assert set((await _job_statuses(sid)).values()) == {"queued"}

    await t.mark_assigned(docs, batch_id="b1", worker_id="w1")
    assert set((await _job_statuses(sid)).values()) == {"running"}
    # source still running while jobs are in flight
    assert await _source_status(sid) == "pending"  # rollup not yet called

    await t.mark_completed(docs, succeeded_urls=urls[:2], failed_urls=urls[2:])
    statuses = await _job_statuses(sid)
    assert statuses[urls[0]] == "success"
    assert statuses[urls[1]] == "success"
    assert statuses[urls[2]] == "failed"
    # at least one succeeded ⇒ source rolls up to success
    assert await _source_status(sid) == "success"


async def test_all_failed_rolls_source_up_to_error(pg):
    from backend.coordinator.job_tracker import JobTracker
    sid = pg
    t = JobTracker()
    urls = ["http://example.test/x", "http://example.test/y"]
    docs = [_Doc(sid, u) for u in urls]

    await t.create_jobs(sid, urls)
    await t.mark_assigned(docs, batch_id="b1", worker_id="w1")
    await t.mark_completed(docs, succeeded_urls=[], failed_urls=urls)

    assert await _source_status(sid) == "error"


async def test_late_worker_cannot_downgrade_success(pg):
    """Idempotency: a reassigned duplicate reporting 'failed' for a url that the
    authoritative worker already marked 'success' must be a no-op."""
    from backend.coordinator.job_tracker import JobTracker
    sid = pg
    t = JobTracker()
    url = "http://example.test/dup"
    docs = [_Doc(sid, url)]

    await t.create_jobs(sid, [url])
    await t.mark_assigned(docs, batch_id="b1", worker_id="w1")
    await t.mark_completed(docs, succeeded_urls=[url], failed_urls=[])
    assert (await _job_statuses(sid))[url] == "success"

    # Late duplicate reports the same doc as failed — must NOT overwrite success.
    await t.mark_completed(docs, succeeded_urls=[], failed_urls=[url])
    assert (await _job_statuses(sid))[url] == "success"


async def test_rollup_waits_for_inflight_jobs(pg):
    """A source with any queued/running job must not be marked terminal yet."""
    from backend.coordinator.job_tracker import JobTracker
    sid = pg
    t = JobTracker()
    urls = ["http://example.test/1", "http://example.test/2"]
    docs = [_Doc(sid, u) for u in urls]

    await t.create_jobs(sid, urls)
    await t.mark_assigned(docs, batch_id="b1", worker_id="w1")
    # Only the first doc completes; the second is still running.
    await t.mark_completed([docs[0]], succeeded_urls=[urls[0]], failed_urls=[])

    # rollup saw a still-running job ⇒ source stays non-terminal
    assert await _source_status(sid) == "pending"
