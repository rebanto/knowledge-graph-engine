from fastapi import APIRouter
from rq import Queue, Worker

from backend.db.redis import get_sync_client

router = APIRouter()


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
