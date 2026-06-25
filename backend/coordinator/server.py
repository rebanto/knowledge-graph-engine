"""
Phase 3 — coordinator gRPC server.

Wraps WorkerRegistry behind the Coordinator service (Register / RequestWork /
Heartbeat / ReportCompletion) and runs a background reaper that declares
silent workers dead and requeues their batches.

Run standalone:
    python -m backend.coordinator.server
"""
import os
import asyncio
import signal
from concurrent import futures

import grpc

from . import coordinator_pb2 as pb
from . import coordinator_pb2_grpc as pb_grpc
from .registry import WorkerRegistry, DocRef
from .job_tracker import JobTracker

HEARTBEAT_SECS = int(os.environ.get("COORDINATOR_HEARTBEAT_SECS", 5))
HEARTBEAT_TIMEOUT = float(os.environ.get("COORDINATOR_HEARTBEAT_TIMEOUT", 30))
REAP_INTERVAL = float(os.environ.get("COORDINATOR_REAP_INTERVAL", 5))
SCHEDULER_INTERVAL = float(os.environ.get("COORDINATOR_SCHEDULER_INTERVAL", 5))


class CoordinatorServicer(pb_grpc.CoordinatorServicer):
    def __init__(self, registry: WorkerRegistry, tracker: JobTracker | None = None):
        self.registry = registry
        # Optional durable bookkeeping. None in unit tests (no DB); the real
        # server injects a JobTracker so ingestion_jobs/sources reflect progress.
        self.tracker = tracker

    async def _track(self, coro) -> None:
        """Run a tracker write best-effort: a Postgres hiccup must never fail the
        RPC or stall the worker — the in-memory registry stays authoritative."""
        try:
            await coro
        except Exception as exc:  # noqa: BLE001
            print(f"[coordinator] job-tracker write failed: {exc!r}")

    async def Register(self, request, context):
        await self.registry.register(request.worker_id, request.host)
        return pb.RegisterResponse(accepted=True, heartbeat_secs=HEARTBEAT_SECS)

    async def RequestWork(self, request, context):
        batch = await self.registry.request_work(request.worker_id, request.max_docs or 1)
        if batch is None:
            return pb.WorkBatch(batch_id="", docs=[])
        if self.tracker:
            await self._track(
                self.tracker.mark_assigned(batch.docs, batch.batch_id, batch.worker_id))
        return pb.WorkBatch(
            batch_id=batch.batch_id,
            docs=[
                pb.DocRef(source_id=d.source_id, document_url=d.document_url,
                          workspace_id=d.workspace_id)
                for d in batch.docs
            ],
        )

    async def Heartbeat(self, request, context):
        keep = await self.registry.heartbeat(
            request.worker_id, request.batch_id, request.status,
            request.completed, request.total)
        if self.tracker and keep:
            await self._track(self.tracker.touch_heartbeat(request.batch_id))
        return pb.HeartbeatAck(keep_going=keep)

    async def GetStatus(self, request, context):
        snap = await self.registry.status_snapshot()
        return pb.ClusterStatus(
            pending=snap["pending"],
            reassignments=snap["reassignments"],
            dead_workers=snap["dead_workers"],
            heartbeat_timeout_secs=snap["heartbeat_timeout_secs"],
            workers=[
                pb.WorkerStatus(
                    worker_id=w["worker_id"],
                    host=w["host"],
                    state=w["state"],
                    batch_id=w["batch_id"],
                    completed=w["completed"],
                    total=w["total"],
                    seconds_since_heartbeat=w["seconds_since_heartbeat"],
                )
                for w in snap["workers"]
            ],
        )

    async def ReportCompletion(self, request, context):
        # Capture the batch's docs BEFORE registry.complete (which is pure but
        # may, in future, drop bookkeeping) so we can map urls → source_id.
        docs = await self.registry.get_batch_docs(request.batch_id)
        ok = await self.registry.complete(
            request.batch_id, request.worker_id,
            list(request.succeeded), list(request.failed))
        # Only the authoritative (non-reassigned) worker's report updates Postgres.
        if self.tracker and ok and docs:
            await self._track(self.tracker.mark_completed(
                docs, list(request.succeeded), list(request.failed)))
        return pb.CompletionAck(received=ok)


async def _reaper(registry: WorkerRegistry, stop: asyncio.Event):
    while not stop.is_set():
        try:
            reaped = await registry.reap_dead()
            if reaped:
                print(f"[coordinator] reaped dead workers: {reaped} "
                      f"(their batches requeued)")
        except Exception as exc:  # never let the reaper die silently
            print(f"[coordinator] reaper error: {exc!r}")
        try:
            await asyncio.wait_for(stop.wait(), timeout=REAP_INTERVAL)
        except asyncio.TimeoutError:
            pass


async def serve(registry: WorkerRegistry | None = None, port: int | None = None,
                with_scheduler: bool = True):
    registry = registry or WorkerRegistry(heartbeat_timeout=HEARTBEAT_TIMEOUT)
    port = port or int(os.environ.get("COORDINATOR_PORT", 50051))
    tracker = JobTracker()

    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=10))
    pb_grpc.add_CoordinatorServicer_to_server(
        CoordinatorServicer(registry, tracker), server)
    server.add_insecure_port(f"[::]:{port}")
    await server.start()
    print(f"[coordinator] listening on :{port} (heartbeat timeout {HEARTBEAT_TIMEOUT}s)")

    stop = asyncio.Event()
    tasks = [asyncio.create_task(_reaper(registry, stop))]

    # The scheduler turns 'pending' sources into work. Without it the pool would
    # register workers and then sit idle forever (the gap this closes). Run it
    # in-process here from the coordinator's import of the existing scheduler.
    if with_scheduler:
        from .scheduler import run_scheduler
        tasks.append(asyncio.create_task(
            run_scheduler(registry, interval=SCHEDULER_INTERVAL,
                          stop=stop, tracker=tracker)))
        print(f"[coordinator] scheduler started (poll every {SCHEDULER_INTERVAL}s)")

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass  # Windows: rely on KeyboardInterrupt

    try:
        await stop.wait()
    finally:
        stop.set()
        await server.stop(grace=3)
        for t in tasks:
            t.cancel()


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass
