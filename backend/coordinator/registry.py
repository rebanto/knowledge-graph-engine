"""
Phase 3 — in-memory worker registry + batch bookkeeping for the coordinator.

This is the heart of the distributed worker pool: it tracks which workers are
alive, which batch each holds, and — when a worker stops heartbeating — declares
it dead and returns its unfinished documents to the pending pool so another
worker can pick them up. Idempotent downstream writes make the resulting
double-processing window harmless.

Pure data structures + asyncio.Lock, no gRPC here, so it can be unit-tested in
isolation (see scripts/coordinator_test.py).
"""
import time
import uuid
import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DocRef:
    source_id: str
    document_url: str
    workspace_id: str


@dataclass
class Worker:
    worker_id: str
    host: str
    last_seen: float
    state: str = "idle"            # idle | processing | dead
    batch_id: Optional[str] = None


@dataclass
class Batch:
    batch_id: str
    docs: list[DocRef]
    worker_id: str
    state: str = "assigned"        # assigned | done | reassigned
    completed: int = 0
    total: int = 0


class WorkerRegistry:
    def __init__(self, heartbeat_timeout: float = 30.0):
        self.heartbeat_timeout = heartbeat_timeout
        self._pending: deque[DocRef] = deque()
        self._workers: dict[str, Worker] = {}
        self._batches: dict[str, Batch] = {}
        self._lock = asyncio.Lock()
        # observability counters (handy for the failure test / dashboards)
        self.reassignments = 0
        self.dead_workers = 0

    # ── Job intake ──────────────────────────────────────────────────────────────

    async def add_documents(self, docs: list[DocRef]) -> None:
        async with self._lock:
            self._pending.extend(docs)

    async def pending_count(self) -> int:
        async with self._lock:
            return len(self._pending)

    # ── Worker lifecycle ────────────────────────────────────────────────────────

    async def register(self, worker_id: str, host: str) -> None:
        async with self._lock:
            self._workers[worker_id] = Worker(
                worker_id=worker_id, host=host, last_seen=time.monotonic())

    async def request_work(self, worker_id: str, max_docs: int) -> Optional[Batch]:
        async with self._lock:
            w = self._workers.get(worker_id)
            if w is None:
                # Unknown/forgotten worker: auto-register so a restarted worker recovers.
                w = Worker(worker_id=worker_id, host="?", last_seen=time.monotonic())
                self._workers[worker_id] = w
            if not self._pending:
                return None
            take = [self._pending.popleft() for _ in range(min(max_docs, len(self._pending)))]
            batch = Batch(
                batch_id=str(uuid.uuid4()), docs=take, worker_id=worker_id,
                total=len(take))
            self._batches[batch.batch_id] = batch
            w.state = "processing"
            w.batch_id = batch.batch_id
            w.last_seen = time.monotonic()
            return batch

    async def heartbeat(self, worker_id: str, batch_id: str,
                        status: str, completed: int, total: int) -> bool:
        """Record liveness. Returns keep_going: False if the batch was taken away
        from this worker (it was declared dead and the batch reassigned)."""
        async with self._lock:
            w = self._workers.get(worker_id)
            if w is not None and w.state != "dead":
                w.last_seen = time.monotonic()
                w.state = status if status in ("idle", "processing") else w.state
            batch = self._batches.get(batch_id)
            if batch is None:
                return True  # nothing to revoke
            if batch.worker_id != worker_id or batch.state == "reassigned":
                return False  # this batch no longer belongs to the heartbeating worker
            batch.completed, batch.total = completed, total
            return True

    async def complete(self, batch_id: str, worker_id: str,
                       succeeded: list[str], failed: list[str]) -> bool:
        async with self._lock:
            batch = self._batches.get(batch_id)
            if batch is None:
                return False
            # A late (reassigned-away) worker reporting completion is ignored —
            # the live worker's run is authoritative. Idempotent writes mean the
            # duplicate work it may have done is harmless.
            if batch.worker_id != worker_id or batch.state == "reassigned":
                return False
            batch.state = "done"
            w = self._workers.get(worker_id)
            if w is not None and w.state != "dead":
                w.state = "idle"
                w.batch_id = None
            return True

    # ── Failure detection ───────────────────────────────────────────────────────

    async def reap_dead(self, now: Optional[float] = None) -> list[str]:
        """Mark workers past the heartbeat timeout as dead and requeue their
        in-flight batch documents. Returns the list of reaped worker ids."""
        now = now if now is not None else time.monotonic()
        reaped: list[str] = []
        async with self._lock:
            for w in list(self._workers.values()):
                if w.state != "processing":
                    # Only reap workers that took a batch and stopped heartbeating.
                    # Idle workers don't send heartbeats; timing them out is a false positive.
                    continue
                if now - w.last_seen <= self.heartbeat_timeout:
                    continue
                w.state = "dead"
                self.dead_workers += 1
                reaped.append(w.worker_id)
                bid = w.batch_id
                w.batch_id = None
                batch = self._batches.get(bid) if bid else None
                if batch and batch.state == "assigned":
                    batch.state = "reassigned"
                    # Requeue every doc in the batch. Re-processing already-done
                    # docs is safe (MERGE/upsert/conditional UPDATE).
                    self._pending.extendleft(reversed(batch.docs))
                    self.reassignments += len(batch.docs)
        return reaped

    async def snapshot(self) -> dict:
        async with self._lock:
            return {
                "pending": len(self._pending),
                "workers": {
                    wid: {"state": w.state, "batch": w.batch_id}
                    for wid, w in self._workers.items()
                },
                "batches": {
                    bid: {"state": b.state, "worker": b.worker_id, "docs": len(b.docs)}
                    for bid, b in self._batches.items()
                },
                "reassignments": self.reassignments,
                "dead_workers": self.dead_workers,
            }
