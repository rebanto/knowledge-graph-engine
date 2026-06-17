import os
from rq import Queue
from dotenv import load_dotenv
from backend.db.redis import get_sync_client

load_dotenv()

_queues: dict[str, Queue] = {}


def get_dlq() -> Queue:
    return get_queue("ingestion_dlq")


def get_queue(name: str = "ingestion") -> Queue:
    """Return (or create) an RQ queue by name.

    Named queues:
      - "ingestion"      : default, user-triggered sources
      - "ingestion_bulk" : lower priority, background re-ingestion
      - "ingestion_dlq"  : dead-letter queue for jobs that exhausted retries
    """
    global _queues
    if name not in _queues:
        _queues[name] = Queue(name, connection=get_sync_client())
    return _queues[name]
