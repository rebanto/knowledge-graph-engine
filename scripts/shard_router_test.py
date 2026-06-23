#!/usr/bin/env python3
"""
Phase 4 verification — exercises backend/db/shard_router.py against 3 live Neo4j
shards (bolt 7687/7688/7689).

Checks:
  1. Consistent hashing distributes entities roughly evenly across shards.
  2. A node is written to exactly the shard its name hashes to (and nowhere else).
  3. A cross-shard edge stores a stub target on the source shard.
  4. Scatter-gather finds the shared neighbour of two entities on different shards.

    python scripts/shard_router_test.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
from collections import Counter

from dotenv import load_dotenv
load_dotenv()

from backend.db.shard_router import ShardRouter, shard_for

WS = "shard_test_ws"
_failures: list[str] = []


def check(cond: bool, label: str):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        _failures.append(label)


async def _node_on_shard(router: ShardRouter, idx: int, name: str) -> bool:
    async with router._drivers[idx].session() as s:
        r = await s.run("MATCH (n {name:$n}) RETURN count(n) AS c", n=name)
        return (await r.single())["c"] > 0


async def main() -> int:
    router = ShardRouter()
    n = router.n
    print(f"Sharding across {n} Neo4j instances.\n")

    # clean prior test data on every shard
    for d in router._drivers:
        async with d.session() as s:
            await s.run("MATCH (x {workspace_id:$ws}) DETACH DELETE x", ws=WS)

    # 1. Distribution
    print("1. Hash distribution over 3000 names")
    dist = Counter(shard_for(f"entity-{i}", n) for i in range(3000))
    spread = max(dist.values()) - min(dist.values())
    print(f"   per-shard counts: {dict(sorted(dist.items()))}  (spread={spread})")
    check(len(dist) == n, "every shard receives entities")
    check(spread < 3000 * 0.10, "distribution within 10% spread (even)")

    # 2. Node placement — find a name per shard, write it, verify location
    print("\n2. Node placement on the computed shard")
    names_by_shard: dict[int, str] = {}
    i = 0
    while len(names_by_shard) < n:
        nm = f"Placement Entity {i}"
        names_by_shard.setdefault(shard_for(nm, n), nm)
        i += 1
    for idx, nm in sorted(names_by_shard.items()):
        await router.merge_node("Concept", nm, WS)
        here = await _node_on_shard(router, idx, nm)
        other = [await _node_on_shard(router, j, nm) for j in range(n) if j != idx]
        check(here and not any(other), f"'{nm}' lives only on shard {idx}")

    # 3 + 4. Cross-shard edge with stub, then scatter-gather
    print("\n3+4. Cross-shard edge, stub, and scatter-gather")
    # pick A and B that hash to different shards, sharing neighbour Z
    a = next(nm for nm in (f"Alpha {k}" for k in range(1000)) if shard_for(nm, n) == 0)
    b = next(nm for nm in (f"Beta {k}" for k in range(1000)) if shard_for(nm, n) == 1)
    z = "Shared Neighbor Z"
    sa, sb, sz = shard_for(a, n), shard_for(b, n), shard_for(z, n)
    print(f"   A='{a}' (shard {sa}), B='{b}' (shard {sb}), Z='{z}' (shard {sz})")

    await router.merge_node("Concept", a, WS)
    await router.merge_node("Concept", b, WS)
    await router.merge_node("Concept", z, WS)
    # A->Z stored on A's shard, B->Z stored on B's shard
    await router.merge_edge(a, "Concept", z, "Concept", "SUPPORTS", WS, {"confidence": 0.9})
    await router.merge_edge(b, "Concept", z, "Concept", "SUPPORTS", WS, {"confidence": 0.9})

    # Z should exist as a stub on shard A (since sz != sa) — verify is_stub flag
    async with router._drivers[sa].session() as s:
        r = await s.run("MATCH (n {name:$z}) RETURN n.is_stub AS stub", z=z)
        rec = await r.single()
    if sz != sa:
        check(rec is not None and rec["stub"] is True,
              f"target stub created on source shard {sa} (is_stub=true)")
    else:
        print("   (Z happens to co-locate with A; stub check N/A)")

    conn = await router.find_connection(a, b)
    print(f"   find_connection -> {conn}")
    check(conn["cross_shard"] is True, "find_connection took the cross-shard path")
    check(z in conn["shared_neighbors"],
          "scatter-gather found the shared neighbour across shards")

    counts = await router.node_counts()
    print(f"\n   non-stub node counts per shard: {counts}")

    # cleanup
    for d in router._drivers:
        async with d.session() as s:
            await s.run("MATCH (x {workspace_id:$ws}) DETACH DELETE x", ws=WS)
            await s.run("MATCH (x {name:$z}) DETACH DELETE x", z=z)
    await router.close()

    print("\n" + "=" * 56)
    if _failures:
        print(f"RESULT: {len(_failures)} CHECK(S) FAILED")
        for f in _failures:
            print("  -", f)
        return 1
    print("RESULT: ALL SHARD-ROUTER CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
