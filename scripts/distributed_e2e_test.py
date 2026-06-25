#!/usr/bin/env python3
"""
Phase 3 end-to-end wiring test — real scheduler + JobTracker + gRPC servicer +
WorkerClient over localhost, against live Postgres. No Docker rebuild, no Gemini,
no network: the source fetch is stubbed to canned documents and the worker's
document processor is a no-op, so this isolates the *coordination* path:

  pending source → scheduler enqueues + creates 'queued' jobs → worker registers,
  pulls batches, heartbeats, processes, reports completion → jobs flip to
  'success' → source rolls up to 'success'.

Auto-skips if Postgres is unavailable. Cleans up its throwaway source + jobs.

    python scripts/distributed_e2e_test.py
"""
import sys
import uuid
import asyncio
from pathlib import Path
from concurrent import futures

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import grpc
from sqlalchemy import select, delete

PORT = 50073
ADDR = f"localhost:{PORT}"
_failures: list[str] = []


def check(cond, label):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        _failures.append(label)


async def main() -> int:
    from backend.db.postgres import AsyncSessionLocal, async_engine
    from backend.db.models import Source, IngestionJob
    from backend.coordinator import scheduler as sched_mod
    from backend.coordinator import coordinator_pb2 as pb
    from backend.coordinator import coordinator_pb2_grpc as pb_grpc
    from backend.coordinator.registry import WorkerRegistry
    from backend.coordinator.server import CoordinatorServicer
    from backend.coordinator.job_tracker import JobTracker
    from backend.coordinator.worker_client import WorkerClient

    await async_engine.dispose(close=False)
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(select(Source.id).limit(1))
    except Exception as e:  # noqa: BLE001
        print(f"SKIP: Postgres unavailable: {e}")
        return 0

    sid = f"dist_e2e_{uuid.uuid4().hex[:8]}"
    urls = [f"http://example.test/{sid}/doc-{i}" for i in range(4)]

    # Stub the source fetch so the real scheduler runs without network/Gemini.
    async def fake_fetch(src):
        return [{"url": u, "title": f"Doc {i}"} for i, u in enumerate(urls)]
    sched_mod.fetch_documents_for_source = fake_fetch

    async with AsyncSessionLocal() as db:
        db.add(Source(id=sid, workspace_id="dist_e2e_ws", type="web_url",
                      url="http://example.test", status="pending"))
        await db.commit()

    registry = WorkerRegistry(heartbeat_timeout=10.0)
    tracker = JobTracker()

    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=10))
    pb_grpc.add_CoordinatorServicer_to_server(
        CoordinatorServicer(registry, tracker), server)
    server.add_insecure_port(f"[::]:{PORT}")
    await server.start()

    stop = asyncio.Event()
    sched_task = asyncio.create_task(
        sched_mod.run_scheduler(registry, interval=1.0, stop=stop, tracker=tracker))

    processed: list[str] = []

    async def stub_process(doc: pb.DocRef):
        processed.append(doc.document_url)
        await asyncio.sleep(0.05)

    worker = WorkerClient(ADDR, stub_process, worker_id="dist-w1", max_docs=2)
    worker_task = asyncio.create_task(worker.run(idle_sleep=0.3))

    # Wait for the source to reach a terminal status (or time out).
    final_status = None
    deadline = asyncio.get_event_loop().time() + 30
    while asyncio.get_event_loop().time() < deadline:
        async with AsyncSessionLocal() as db:
            final_status = (await db.execute(
                select(Source.status).where(Source.id == sid))).scalar_one()
        if final_status in ("success", "error"):
            break
        await asyncio.sleep(0.5)

    # ── teardown ────────────────────────────────────────────────────────────────
    worker.stop()
    stop.set()
    worker_task.cancel()
    sched_task.cancel()
    await server.stop(grace=1)

    async with AsyncSessionLocal() as db:
        job_rows = (await db.execute(
            select(IngestionJob.document_url, IngestionJob.status)
            .where(IngestionJob.source_id == sid))).all()
    job_statuses = {u: s for u, s in job_rows}

    print(f"\n  processed by worker: {sorted(processed)}")
    print(f"  job statuses: {job_statuses}")
    print(f"  final source status: {final_status}")

    check(sorted(set(processed)) == sorted(urls), "worker processed all 4 documents")
    check(len(job_statuses) == 4, "one ingestion_jobs row per document")
    check(all(s == "success" for s in job_statuses.values()),
          "every job marked success")
    check(final_status == "success", "source rolled up to success")

    # cleanup
    async with AsyncSessionLocal() as db:
        await db.execute(delete(IngestionJob).where(IngestionJob.source_id == sid))
        await db.execute(delete(Source).where(Source.id == sid))
        await db.commit()

    print("\n" + "=" * 54)
    if _failures:
        print(f"RESULT: {len(_failures)} CHECK(S) FAILED")
        for f in _failures:
            print("  -", f)
        return 1
    print("RESULT: ALL DISTRIBUTED E2E WIRING CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
