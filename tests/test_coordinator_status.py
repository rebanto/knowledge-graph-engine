"""Tests for the Phase 6 coordinator dashboard status path.

Spins an in-process coordinator gRPC server (no Docker) with a seeded registry
and asserts GetStatus reports pool counters and per-worker progress, and that
the API endpoint degrades gracefully to {available: false} when no coordinator
is listening.
"""
from concurrent import futures

import grpc
import pytest

from backend.coordinator import coordinator_pb2 as pb
from backend.coordinator import coordinator_pb2_grpc as pb_grpc
from backend.coordinator.registry import WorkerRegistry, DocRef
from backend.coordinator.server import CoordinatorServicer

pytestmark = pytest.mark.asyncio

PORT = 50079


async def _seeded_registry() -> WorkerRegistry:
    reg = WorkerRegistry(heartbeat_timeout=30.0)
    await reg.add_documents([
        DocRef(source_id="s1", document_url=f"doc-{i}", workspace_id="w1")
        for i in range(5)
    ])
    await reg.register("worker-a", "host-a")
    await reg.register("worker-b", "host-b")
    # worker-a takes a 2-doc batch and reports partial progress
    batch = await reg.request_work("worker-a", max_docs=2)
    await reg.heartbeat("worker-a", batch.batch_id, "processing", 1, 2)
    return reg


async def test_get_status_reports_workers_and_counters():
    reg = await _seeded_registry()
    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=4))
    pb_grpc.add_CoordinatorServicer_to_server(CoordinatorServicer(reg), server)
    server.add_insecure_port(f"[::]:{PORT}")
    await server.start()
    try:
        async with grpc.aio.insecure_channel(f"localhost:{PORT}") as ch:
            stub = pb_grpc.CoordinatorStub(ch)
            status = await stub.GetStatus(pb.StatusRequest(), timeout=3)
    finally:
        await server.stop(grace=0)

    assert status.pending == 3                 # 5 queued − 2 taken
    assert status.heartbeat_timeout_secs == 30
    workers = {w.worker_id: w for w in status.workers}
    assert set(workers) == {"worker-a", "worker-b"}
    assert workers["worker-a"].state == "processing"
    assert workers["worker-a"].completed == 1
    assert workers["worker-a"].total == 2
    assert workers["worker-a"].host == "host-a"
    assert workers["worker-b"].state == "idle"
    assert workers["worker-a"].seconds_since_heartbeat >= 0.0


async def test_endpoint_marshals_status(monkeypatch):
    """The /system/coordinator handler shapes the gRPC reply into JSON."""
    import backend.api.routes.system as sysmod

    reg = await _seeded_registry()
    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=4))
    pb_grpc.add_CoordinatorServicer_to_server(CoordinatorServicer(reg), server)
    server.add_insecure_port(f"[::]:{PORT + 1}")
    await server.start()
    monkeypatch.setenv("COORDINATOR_HOST", "localhost")
    monkeypatch.setenv("COORDINATOR_PORT", str(PORT + 1))
    try:
        body = await sysmod.coordinator_status()
    finally:
        await server.stop(grace=0)

    assert body["available"] is True
    assert body["pending"] == 3
    assert body["worker_count"] == 2
    assert body["live_worker_count"] == 2
    a = next(w for w in body["workers"] if w["worker_id"] == "worker-a")
    assert a["completed"] == 1 and a["total"] == 2


async def test_endpoint_unavailable_when_coordinator_down(monkeypatch):
    import backend.api.routes.system as sysmod
    # Point at a port with nothing listening — must degrade, not raise.
    monkeypatch.setenv("COORDINATOR_HOST", "localhost")
    monkeypatch.setenv("COORDINATOR_PORT", "59999")
    body = await sysmod.coordinator_status()
    assert body == {"available": False}
