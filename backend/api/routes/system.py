import os

import grpc
from fastapi import APIRouter
from rq import Queue, Worker

from backend.db.redis import get_sync_client
from backend.coordinator import coordinator_pb2 as pb
from backend.coordinator import coordinator_pb2_grpc as pb_grpc

router = APIRouter()


def _coordinator_addresses() -> list[str]:
    """Where to look for the coordinator's gRPC port.

    In Docker the coordinator is reachable by its service name; a host-run API
    (dev.ps1) reaches the same container on the published localhost port. Try the
    configured host first, then localhost, so the dashboard works in both setups.
    """
    host = os.environ.get("COORDINATOR_HOST", "localhost")
    port = os.environ.get("COORDINATOR_PORT", "50051")
    candidates = [f"{host}:{port}"]
    if host not in ("localhost", "127.0.0.1"):
        candidates.append(f"localhost:{port}")
    return candidates


async def _fetch_cluster_status(timeout: float = 2.0):
    """Call GetStatus on the first reachable coordinator address, or None."""
    for addr in _coordinator_addresses():
        try:
            async with grpc.aio.insecure_channel(addr) as channel:
                stub = pb_grpc.CoordinatorStub(channel)
                return await stub.GetStatus(pb.StatusRequest(), timeout=timeout)
        except Exception:
            continue
    return None


@router.get("/system/queue")
def queue_status():
    """RQ worker health and queue depths — used by the Sources UI to show worker state."""
    conn = get_sync_client()

    workers = Worker.all(connection=conn)
    worker_info = [
        {
            "name": w.name,
            "state": w.get_state(),
            "queues": [q.name for q in w.queues],
            "current_job_id": w.get_current_job_id(),
        }
        for w in workers
    ]

    queue_info = {}
    for name in ["ingestion", "ingestion_bulk", "ingestion_dlq"]:
        q = Queue(name, connection=conn)
        queue_info[name] = {
            "queued": q.count,
            "started": q.started_job_registry.count,
            "failed": q.failed_job_registry.count,
        }

    return {
        "worker_count": len(worker_info),
        "workers": worker_info,
        "queues": queue_info,
    }


@router.get("/system/coordinator")
async def coordinator_status():
    """Live status of the Phase 3 distributed worker pool, for the dashboard.

    Returns {available: false} when the coordinator isn't running (the default
    local setup uses the single RQ worker) so the UI can show a calm 'not
    enabled' state instead of an error.
    """
    status = await _fetch_cluster_status()
    if status is None:
        return {"available": False}

    workers = [
        {
            "worker_id": w.worker_id,
            "host": w.host,
            "state": w.state,
            "batch_id": w.batch_id or None,
            "completed": w.completed,
            "total": w.total,
            "seconds_since_heartbeat": round(w.seconds_since_heartbeat, 1),
        }
        for w in status.workers
    ]
    live = sum(1 for w in workers if w["state"] != "dead")
    return {
        "available": True,
        "pending": status.pending,
        "reassignments": status.reassignments,
        "dead_workers": status.dead_workers,
        "heartbeat_timeout_secs": status.heartbeat_timeout_secs,
        "worker_count": len(workers),
        "live_worker_count": live,
        "workers": workers,
    }
