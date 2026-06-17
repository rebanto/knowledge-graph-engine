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
    queue = Queue("ingestion", connection=conn)
    print("Ingestion worker listening on queue 'ingestion'...")
    # SimpleWorker runs jobs in-process instead of forking — required on
    # Windows, since rq's default Worker relies on os.fork().
    worker = SimpleWorker([queue], connection=conn)
    worker.work()
