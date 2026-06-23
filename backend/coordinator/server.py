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

HEARTBEAT_SECS = int(os.environ.get("COORDINATOR_HEARTBEAT_SECS", 5))
HEARTBEAT_TIMEOUT = float(os.environ.get("COORDINATOR_HEARTBEAT_TIMEOUT", 30))
REAP_INTERVAL = float(os.environ.get("COORDINATOR_REAP_INTERVAL", 5))


class CoordinatorServicer(pb_grpc.CoordinatorServicer):
    def __init__(self, registry: WorkerRegistry):
        self.registry = registry

    async def Register(self, request, context):
        await self.registry.register(request.worker_id, request.host)
        return pb.RegisterResponse(accepted=True, heartbeat_secs=HEARTBEAT_SECS)

    async def RequestWork(self, request, context):
        batch = await self.registry.request_work(request.worker_id, request.max_docs or 1)
        if batch is None:
            return pb.WorkBatch(batch_id="", docs=[])
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
        return pb.HeartbeatAck(keep_going=keep)

    async def ReportCompletion(self, request, context):
        ok = await self.registry.complete(
            request.batch_id, request.worker_id,
            list(request.succeeded), list(request.failed))
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


async def serve(registry: WorkerRegistry | None = None, port: int | None = None):
    registry = registry or WorkerRegistry(heartbeat_timeout=HEARTBEAT_TIMEOUT)
    port = port or int(os.environ.get("COORDINATOR_PORT", 50051))

    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=10))
    pb_grpc.add_CoordinatorServicer_to_server(CoordinatorServicer(registry), server)
    server.add_insecure_port(f"[::]:{port}")
    await server.start()
    print(f"[coordinator] listening on :{port} (heartbeat timeout {HEARTBEAT_TIMEOUT}s)")

    stop = asyncio.Event()
    reaper = asyncio.create_task(_reaper(registry, stop))

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
        reaper.cancel()


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass
