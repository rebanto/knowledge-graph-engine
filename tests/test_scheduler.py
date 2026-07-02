"""Live Postgres test for the coordinator scheduler's intake step.

pull_pending_once is what turns a 'pending' source into work: it expands the
source into documents, loads them into the registry, marks the source 'running'
so it isn't double-scheduled, and (with a tracker) pre-creates one 'queued'
ingestion_jobs row per document. The document fetch is stubbed so the test is
deterministic and offline.

Auto-skips if Postgres is unavailable; cleans up its throwaway source + jobs.
"""
import uuid

import pytest
from sqlalchemy import select, delete

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def pg_source():
    from backend.db.postgres import AsyncSessionLocal, async_engine
    from backend.db.models import Source, IngestionJob
    # Rebind the module-global engine pool to this test's event loop. Without
    # this, when a prior test's loop has closed, the fixture's write and
    # pull_pending_once's read run against a pool bound to the dead loop and the
    # just-created 'pending' source isn't seen (enqueued comes back 0). Same
    # rationale as test_job_tracker's pg fixture.
    await async_engine.dispose(close=False)
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(select(Source.id).limit(1))
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Postgres unavailable: {e}")

    sid = f"sched_test_{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        db.add(Source(id=sid, workspace_id="sched_ws", type="web_url",
                      url="http://example.test", status="pending"))
        await db.commit()
    yield sid
    async with AsyncSessionLocal() as db:
        await db.execute(delete(IngestionJob).where(IngestionJob.source_id == sid))
        await db.execute(delete(Source).where(Source.id == sid))
        await db.commit()


async def test_pull_pending_enqueues_marks_running_and_creates_jobs(pg_source, monkeypatch):
    from backend.coordinator import scheduler as sched
    from backend.coordinator.registry import WorkerRegistry
    from backend.coordinator.job_tracker import JobTracker
    from backend.db.postgres import AsyncSessionLocal
    from backend.db.models import Source, IngestionJob
    sid = pg_source

    urls = [f"http://example.test/{sid}/d{i}" for i in range(3)]

    async def fake_fetch(src):
        return [{"url": u} for u in urls]
    monkeypatch.setattr(sched, "fetch_documents_for_source", fake_fetch)

    registry = WorkerRegistry()
    tracker = JobTracker()
    enqueued = await sched.pull_pending_once(registry, tracker)

    # Only our throwaway source is guaranteed pending; assert at least our docs.
    assert enqueued >= 3
    assert await registry.pending_count() >= 3

    async with AsyncSessionLocal() as db:
        status = (await db.execute(
            select(Source.status).where(Source.id == sid))).scalar_one()
        jobs = (await db.execute(
            select(IngestionJob.document_url, IngestionJob.status)
            .where(IngestionJob.source_id == sid))).all()

    assert status == "running", "source not marked running after scheduling"
    assert {u for u, _ in jobs} == set(urls), "a queued job per document not created"
    assert all(s == "queued" for _, s in jobs)


async def test_pull_pending_without_tracker_creates_no_jobs(pg_source, monkeypatch):
    """Backwards-compatible: the unit failure-test path passes no tracker and
    must not touch Postgres job rows."""
    from backend.coordinator import scheduler as sched
    from backend.coordinator.registry import WorkerRegistry
    from backend.db.postgres import AsyncSessionLocal
    from backend.db.models import IngestionJob
    sid = pg_source

    async def fake_fetch(src):
        return [{"url": f"http://example.test/{sid}/only"}]
    monkeypatch.setattr(sched, "fetch_documents_for_source", fake_fetch)

    await sched.pull_pending_once(WorkerRegistry(), tracker=None)

    async with AsyncSessionLocal() as db:
        count = len((await db.execute(
            select(IngestionJob.id).where(IngestionJob.source_id == sid))).all())
    assert count == 0
