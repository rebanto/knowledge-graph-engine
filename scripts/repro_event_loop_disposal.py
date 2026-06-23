#!/usr/bin/env python3
"""
Reproduction for the RQ SimpleWorker "Event loop is closed" regression.

The ingestion worker (scripts/ingestion_worker.py) is an RQ SimpleWorker, so it
runs every job in ONE long-lived process via a fresh asyncio.run() per job. A
module-global redis.asyncio client binds its connection pool to the event loop
that created it. If the client is not closed before that loop is torn down, the
NEXT job's loop inherits the stale pool and fails with
"RuntimeError: Event loop is closed".

This script simulates two sequential jobs exactly the way SimpleWorker would,
using the real module-global client in backend/db/redis.py.

    python scripts/repro_event_loop_disposal.py            # uses the fix (passes)
    python scripts/repro_event_loop_disposal.py --no-fix   # skips teardown (fails)

Requires Redis to be running (redis://localhost:6379 by default).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
from dotenv import load_dotenv
load_dotenv()

from backend.db import redis as redis_db

USE_FIX = "--no-fix" not in sys.argv


async def _job(n: int) -> None:
    """Touch the module-global async Redis client, like a real job would."""
    client = redis_db.get_async_client()
    await client.set(f"repro:job:{n}", "1", ex=60)
    val = await client.get(f"repro:job:{n}")
    assert val == "1"
    if USE_FIX:
        # This is the restored per-job teardown. Without it, job 2 crashes.
        await redis_db.close_async_client()


def run_job(n: int) -> None:
    """Mimic SimpleWorker: a fresh event loop per job, same process."""
    asyncio.run(_job(n))


def main() -> int:
    print(f"Running two sequential jobs (fix {'ENABLED' if USE_FIX else 'DISABLED'})...")
    run_job(1)
    print("  job 1: OK")
    try:
        run_job(2)
    except RuntimeError as exc:
        print(f"  job 2: FAILED -> {exc!r}")
        print("\nRESULT: reproduced the regression (second job died on the stale loop).")
        return 1
    print("  job 2: OK")
    print("\nRESULT: both jobs completed — per-job teardown works.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
