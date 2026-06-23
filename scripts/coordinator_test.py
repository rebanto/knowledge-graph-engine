#!/usr/bin/env python3
"""
Phase 3 verification — the distributed-worker failure test, automated and
in-process (real gRPC over localhost, no Docker required).

Scenario:
  - 6 documents are queued.
  - A "bad" worker registers, grabs a 5-doc batch, then goes silent (simulated
    crash: no heartbeats, never reports completion).
  - A "good" worker processes the remaining doc, then keeps asking for work.
  - After the heartbeat timeout the coordinator's reaper declares the bad worker
    dead and requeues its 5 docs; the good worker picks them up.

Asserts: every distinct document is ultimately processed (nothing lost), the
coordinator recorded a reassignment, and the bad worker was reaped.

    python scripts/coordinator_test.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
from concurrent import futures

import grpc

from backend.coordinator import coordinator_pb2 as pb
from backend.coordinator import coordinator_pb2_grpc as pb_grpc
from backend.coordinator.registry import WorkerRegistry, DocRef
from backend.coordinator.server import CoordinatorServicer
from backend.coordinator.worker_client import WorkerClient

PORT = 50071
ADDR = f"localhost:{PORT}"
_failures: list[str] = []


def check(cond, label):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        _failures.append(label)


async def main() -> int:
    registry = WorkerRegistry(heartbeat_timeout=3.0)
    docs = [DocRef(source_id="s1", document_url=f"doc-{i}", workspace_id="w1")
            for i in range(6)]
    await registry.add_documents(docs)

    # ── start coordinator gRPC server + reaper ──────────────────────────────────
    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=10))
    pb_grpc.add_CoordinatorServicer_to_server(CoordinatorServicer(registry), server)
    server.add_insecure_port(f"[::]:{PORT}")
    await server.start()

    stop_reaper = asyncio.Event()

    async def reaper():
        while not stop_reaper.is_set():
            reaped = await registry.reap_dead()
            if reaped:
                print(f"  coordinator reaped: {reaped}")
            try:
                await asyncio.wait_for(stop_reaper.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                pass
    reaper_task = asyncio.create_task(reaper())

    processed: dict[str, int] = {}
    lock = asyncio.Lock()

    async def good_process(doc: pb.DocRef):
        async with lock:
            processed[doc.document_url] = processed.get(doc.document_url, 0) + 1
        await asyncio.sleep(0.3)  # simulate work

    # ── bad worker: register + grab a big batch, then go silent ─────────────────
    async def bad_worker():
        async with grpc.aio.insecure_channel(ADDR) as ch:
            stub = pb_grpc.CoordinatorStub(ch)
            await stub.Register(pb.RegisterRequest(worker_id="bad", host="bad"))
            batch = await stub.RequestWork(pb.WorkRequest(worker_id="bad", max_docs=5))
            print(f"  bad worker grabbed {len(batch.docs)} docs then 'crashed' "
                  f"(no more heartbeats)")
            # never heartbeat, never complete — simulate a hard crash
            await asyncio.sleep(30)

    bad_task = asyncio.create_task(bad_worker())
    await asyncio.sleep(0.5)  # let the bad worker grab its batch first

    # ── good worker: small batches, keeps working ───────────────────────────────
    good = WorkerClient(ADDR, good_process, worker_id="good", max_docs=1)
    good_task = asyncio.create_task(good.run(idle_sleep=0.3))

    # run long enough for: good to drain the 1 leftover, timeout(3s) to fire,
    # reassignment, then good to drain the 5 requeued docs.
    deadline = asyncio.get_event_loop().time() + 18
    while asyncio.get_event_loop().time() < deadline:
        async with lock:
            done = len(processed)
        if done >= 6:
            break
        await asyncio.sleep(0.5)

    # ── shut everything down ────────────────────────────────────────────────────
    good.stop()
    bad_task.cancel()
    good_task.cancel()
    stop_reaper.set()
    reaper_task.cancel()
    await server.stop(grace=1)

    snap = await registry.snapshot()
    print(f"\n  processed counts: {processed}")
    print(f"  registry: reassignments={snap['reassignments']} "
          f"dead_workers={snap['dead_workers']} pending={snap['pending']}")

    check(len(processed) == 6, "all 6 distinct documents were processed (nothing lost)")
    check(snap["dead_workers"] >= 1, "the crashed worker was reaped")
    check(snap["reassignments"] >= 5, "the crashed worker's batch was requeued")
    check(snap["workers"].get("bad", {}).get("state") == "dead", "bad worker marked dead")

    print("\n" + "=" * 54)
    if _failures:
        print(f"RESULT: {len(_failures)} CHECK(S) FAILED")
        for f in _failures:
            print("  -", f)
        return 1
    print("RESULT: ALL COORDINATOR FAILURE-TEST CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
