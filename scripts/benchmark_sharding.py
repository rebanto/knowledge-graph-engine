#!/usr/bin/env python3
"""
Phase 4 benchmark — single-node vs 2-shard vs 3-shard query latency.

Uses the same ShardRouter with num_shards = 1 / 2 / 3 over the live Neo4j
instances on bolt 7687/7688/7689 (shard count 1 = single-node baseline).

Measures:
  - Single-entity lookup latency (p50, p99)
  - Cross-shard relationship query latency (p50, p99)  [N/A for single-node]

Writes results into an isolated benchmark workspace and cleans up afterwards.

    python scripts/benchmark_sharding.py [--entities N] [--queries Q]
"""
import sys
import time
import asyncio
import argparse
import statistics
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from backend.db.shard_router import ShardRouter

WS = "benchmark_ws"


def pct(values, p):
    if not values:
        return float("nan")
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((p / 100) * (len(s) - 1)))))
    return s[k] * 1000  # -> ms


async def _seed(router: ShardRouter, n_entities: int):
    # entities
    names = [f"BenchEntity-{i}" for i in range(n_entities)]
    await asyncio.gather(*(router.merge_node("Concept", nm, WS) for nm in names))
    # edges: chain + some cross links so relationship queries have paths
    edges = []
    for i in range(n_entities - 1):
        edges.append((names[i], names[i + 1]))
        if i + 5 < n_entities:
            edges.append((names[i], names[i + 5]))
    await asyncio.gather(*(
        router.merge_edge(a, "Concept", b, "Concept", "SUPPORTS", WS, {"confidence": 0.9})
        for a, b in edges
    ))
    return names


async def _clean(router: ShardRouter):
    for d in router._drivers:
        async with d.session() as s:
            await s.run("MATCH (n {workspace_id:$ws}) DETACH DELETE n", ws=WS)


async def bench_config(n_shards: int, n_entities: int, n_queries: int) -> dict:
    router = ShardRouter(shards=n_shards)
    await _clean(router)
    names = await _seed(router, n_entities)

    # single-entity lookups
    lookups = []
    for i in range(n_queries):
        nm = names[i % len(names)]
        t = time.perf_counter()
        await router.get_entity(nm)
        lookups.append(time.perf_counter() - t)

    # relationship queries between random pairs (cross-shard when n_shards > 1)
    rels = []
    cross = 0
    for i in range(n_queries):
        a = names[i % len(names)]
        b = names[(i * 7 + 3) % len(names)]
        t = time.perf_counter()
        res = await router.find_connection(a, b)
        rels.append(time.perf_counter() - t)
        if res.get("cross_shard"):
            cross += 1

    await _clean(router)
    await router.close()

    return {
        "shards": n_shards,
        "lookup_p50": pct(lookups, 50),
        "lookup_p99": pct(lookups, 99),
        "rel_p50": pct(rels, 50),
        "rel_p99": pct(rels, 99),
        "cross_pct": 100.0 * cross / max(1, n_queries),
    }


async def main(n_entities: int, n_queries: int) -> int:
    print(f"Benchmark: {n_entities} entities, {n_queries} queries per config\n")
    results = []
    for n in (1, 2, 3):
        print(f"running {n}-shard config...")
        results.append(await bench_config(n, n_entities, n_queries))

    hdr = f"{'Query type':<34}{'Single':>10}{'2-shard':>10}{'3-shard':>10}"
    print("\n" + hdr)
    print("-" * len(hdr))
    by = {r["shards"]: r for r in results}

    def row(label, key, na_single=False):
        cells = []
        for n in (1, 2, 3):
            if na_single and n == 1:
                cells.append(f"{'N/A':>10}")
            else:
                cells.append(f"{by[n][key]:>10.2f}")
        print(f"{label:<34}" + "".join(cells))

    row("Single-entity lookup p50 (ms)", "lookup_p50")
    row("Single-entity lookup p99 (ms)", "lookup_p99")
    row("Relationship query p50 (ms)", "rel_p50")
    row("Relationship query p99 (ms)", "rel_p99")
    print(f"\ncross-shard fraction of relationship queries: "
          f"2-shard={by[2]['cross_pct']:.0f}%, 3-shard={by[3]['cross_pct']:.0f}%")
    print("\n(Single-node relationship queries run on one instance; the multi-shard "
          "rows include scatter-gather overhead for cross-shard pairs.)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--entities", type=int, default=300)
    ap.add_argument("--queries", type=int, default=200)
    args = ap.parse_args()
    raise SystemExit(asyncio.run(main(args.entities, args.queries)))
