#!/usr/bin/env python3
"""
Background worker that processes ingestion jobs from the Redis queue.
Run this in its own terminal alongside the FastAPI backend:
    python scripts/ingestion_worker.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from redis import Redis
from rq import Queue
from rq.worker import SimpleWorker

if __name__ == "__main__":
    conn = Redis.from_url(os.environ["REDIS_URL"])
    queues = [
        Queue("ingestion", connection=conn),
        Queue("ingestion_bulk", connection=conn),
    ]
    print("Ingestion worker listening on: ingestion, ingestion_bulk")
    # SimpleWorker runs jobs in-process (no forking) — required on Windows
    # because rq's default Worker uses os.fork() which doesn't exist on Windows.
    worker = SimpleWorker(queues, connection=conn)
    worker.work()
