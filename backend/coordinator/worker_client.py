"""
Phase 3 — worker-side gRPC client.

Registers with the coordinator, repeatedly requests a batch, processes each
document while heartbeating every few seconds, and reports completion. On a
HeartbeatAck with keep_going=False (the coordinator declared this worker dead
and reassigned the batch) the worker drops the batch and asks for fresh work.

The document processor is injected so production can use the real
process_document pipeline while tests use a controllable stub.
"""
import os
import asyncio
import socket
from typing import Awaitable, Callable, Optional

import grpc

from . import coordinator_pb2 as pb
from . import coordinator_pb2_grpc as pb_grpc

# A processor takes a DocRef-like message and returns None (success) or raises.
ProcessFn = Callable[[pb.DocRef], Awaitable[None]]


class WorkerClient:
    def __init__(self, address: str, process_fn: ProcessFn,
                 worker_id: Optional[str] = None, max_docs: int = 5):
        self.address = address
        self.process_fn = process_fn
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}"
        self.max_docs = max_docs
        self.heartbeat_secs = 5
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def run(self, idle_sleep: float = 1.0) -> None:
        retry_delay = 2.0
        while not self._stop.is_set():
            try:
                await self._run_session(idle_sleep)
            except grpc.aio.AioRpcError:
                if self._stop.is_set():
                    return
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30.0)
            else:
                retry_delay = 2.0

    async def _run_session(self, idle_sleep: float = 1.0) -> None:
        async with grpc.aio.insecure_channel(self.address) as channel:
            stub = pb_grpc.CoordinatorStub(channel)
            resp = await stub.Register(
                pb.RegisterRequest(worker_id=self.worker_id, host=socket.gethostname()))
            self.heartbeat_secs = resp.heartbeat_secs or 5

            while not self._stop.is_set():
                batch = await stub.RequestWork(
                    pb.WorkRequest(worker_id=self.worker_id, max_docs=self.max_docs))
                if not batch.batch_id or not batch.docs:
                    await asyncio.sleep(idle_sleep)
                    continue
                await self._process_batch(stub, batch)

    async def _process_batch(self, stub, batch) -> None:
        succeeded: list[str] = []
        failed: list[str] = []
        revoked = False

        async def _heartbeat_loop():
            nonlocal revoked
            while not revoked and not self._stop.is_set():
                ack = await stub.Heartbeat(pb.HeartbeatRequest(
                    worker_id=self.worker_id, batch_id=batch.batch_id,
                    status="processing", completed=len(succeeded), total=len(batch.docs)))
                if not ack.keep_going:
                    revoked = True
                    return
                await asyncio.sleep(self.heartbeat_secs)

        hb = asyncio.create_task(_heartbeat_loop())
        try:
            for doc in batch.docs:
                if revoked or self._stop.is_set():
                    break
                try:
                    await self.process_fn(doc)
                    succeeded.append(doc.document_url)
                except Exception:
                    failed.append(doc.document_url)
        finally:
            revoked = True
            hb.cancel()

        if not revoked or succeeded or failed:
            try:
                await stub.ReportCompletion(pb.BatchResult(
                    batch_id=batch.batch_id, worker_id=self.worker_id,
                    succeeded=succeeded, failed=failed))
            except Exception:
                pass


async def _real_process(doc: pb.DocRef) -> None:
    """Production processor: fetch one document and run the existing pipeline."""
    from backend.ingestion.entity_resolver import EntityResolver
    from backend.ingestion.worker import process_document
    from backend.ingestion.dispatcher import fetch_documents_for_source
    from backend.db.postgres import AsyncSessionLocal
    from backend.db.models import Source
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        src = (await db.execute(
            select(Source).where(Source.id == doc.source_id))).scalar_one_or_none()
    if src is None:
        return
    docs = await fetch_documents_for_source(src)
    target = next((d for d in docs if d.get("url") == doc.document_url), None)
    if target is None:
        return
    resolver = EntityResolver()
    await resolver.load_from_redis(doc.workspace_id)
    await process_document(target, doc.workspace_id, resolver)
    await resolver.flush_to_redis(doc.workspace_id)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    host = os.environ.get("COORDINATOR_HOST", "localhost")
    port = os.environ.get("COORDINATOR_PORT", "50051")
    client = WorkerClient(f"{host}:{port}", _real_process)
    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        pass
