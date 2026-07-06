# 10 — Sharded knowledge graph (Phase 4)

**Status: implemented, opt-in via `USE_SHARDING=true`.** The single-Neo4j path
([`db/neo4j.py`](../backend/db/neo4j.py)) remains the default and the fallback.
The shard router presents the **same write surface**
(`merge_node/merge_edge/merge_paper/mark_paper_processed`) so the ingestion
pipeline is byte-for-byte identical regardless of physical layout — only the
graph *placement* changes.

Code: [`backend/db/shard_router.py`](../backend/db/shard_router.py).

## Why

A single Neo4j instance is both a throughput ceiling and a durability single
point of failure. Sharding splits the entity space across N instances. The cost:
cross-shard relationship queries need a scatter-gather step (more latency, more
code). The benchmark below produces real data to judge whether that trade is
worth it at your scale — and at this scale, **it is not** (see
[Benchmark](#benchmark-results)).

## Consistent hashing

Every entity maps to a shard by:

```
shard = int(sha256(entity_name.strip().lower()).hexdigest(), 16) % num_shards
```

- **Deterministic:** the same entity always lands on the same shard — no routing
  table is consulted at query time; any component computes the shard from the
  name alone.
- **Uniform:** SHA-256 output is uniform, so shards hold roughly equal counts.
- **Papers route by `arxiv_id`** (not title) so id-keyed lookups are O(1).

`NUM_SHARDS` (default 3) is fixed at init. **Do not change it after data is
written** — resharding requires a migration that moves entities to their new
shard. Per-shard URIs come from `NEO4J_SHARD_{i}_URI` or default to
`bolt://localhost:{7687+i}`.

## The shard router

`ShardRouter` holds one async Neo4j driver per shard (pool size 20 each).

### Single-entity operations
`merge_node`, `merge_paper`, `get_entity`, `is_paper_processed`,
`mark_paper_processed` compute the owning shard and hit **exactly one** shard.
Nodes carry `shard_id` and `is_stub` (false for real nodes), plus the same
idempotent `source_ids` attribution as the single-node path.

### Cross-shard edges & stub nodes
An edge is stored on the **source entity's shard**. If the target lives on a
different shard, a lightweight **stub** target node (`is_stub=true`, name/type
only) is `MERGE`d locally so the relationship is traversable on the source
shard; the full target node lives on its owning shard. `merge_edge` does this in
two steps (ensure the (possibly stub) target exists, then merge the
relationship). `node_counts()` excludes stubs so counts aren't double-reported.

### Scatter-gather: `find_connection(a, b)`
"How is A connected to B?":

```
sa, sb = shard_for(a), shard_for(b)
if sa == sb:
    # both on one shard → a single local query handles any path length
    MATCH (x{name:a}),(y{name:b}) OPTIONAL MATCH (x)--(z)--(y) …
    return {cross_shard:false, direct, shared_neighbors}
else:
    # scatter: pull each endpoint's 1-hop neighbour set from its own shard,
    # IN PARALLEL (asyncio.gather), then intersect for two-hop paths
    na, nb = await gather(neighbors(sa,a), neighbors(sb,b))
    return {cross_shard:true, direct: b in na or a in nb, shared_neighbors: sorted(na & nb)}
```

The plan describes expanding the scatter one hop at a time for deeper paths; the
current implementation resolves the **direct** and **two-hop (shared-neighbour)**
cases, which covers the common "how are these connected" question.

## Running it

```powershell
# bring up shards 1 and 2 (the default 'neo4j' service is shard 0)
docker compose --profile sharding up -d
# enable in .env
USE_SHARDING=true
NUM_SHARDS=3
```

When enabled, [`worker._graph()`](../backend/ingestion/worker.py) routes writes
through the router. **Conflict detection is skipped under sharding** (the two
endpoints of a SUPPORTS/CONTRADICTS pair may live on different shards); the
single-node path keeps full inline detection.

## Benchmark results

Run by [`scripts/benchmark_sharding.py`](../scripts/benchmark_sharding.py)
(`--entities 300 --queries 200`), comparing shard counts 1/2/3 over the same
three Neo4j 5.18 instances. Measured 2026-06-22 on the local setup:

| Query type | Single | 2-shard | 3-shard |
|------------|--------|---------|---------|
| Single-entity lookup p50 (ms) | 3.29 | 3.61 | 3.99 |
| Single-entity lookup p99 (ms) | 6.49 | 8.59 | 8.90 |
| Relationship query p50 (ms) | 13.41 | 4.84 | 5.64 |
| Relationship query p99 (ms) | 26.33 | 23.48 | 33.40 |
| Cross-shard fraction of rel Qs | N/A | 50% | 68% |

Reading it:
- **Single-entity lookups** get marginally slower per shard (extra driver hop, no
  scatter) — negligible in absolute terms.
- **Relationship queries** are *faster* at p50 under sharding (each shard holds a
  third of the graph, so the local neighbour scan is cheaper and the two halves
  run in parallel). The p99 tail grows at 3 shards because scatter-gather waits
  on the slowest of more shards.
- **Ingestion throughput** is not graph-bound — it's dominated by per-document
  Gemini latency (seconds), which dwarfs sub-10ms graph writes — so sharding
  doesn't move it.

**Conclusion at this scale (hundreds of entities): sharding is _not_ worth the
operational/cost overhead** — single-node latencies are already low. Sharding
pays off only once a single instance becomes a real write/throughput or
durability ceiling. Re-run the benchmark at production scale before deciding.

## Phase 7 deployment note

The card-free production target is one Hugging Face Docker Space with Neo4j
AuraDB Free, not a sharded managed graph service. Production therefore runs with
`USE_SHARDING=false`. Keep the shard router as a local benchmarkable option and
re-run this script at production scale before adding operational complexity.

## Test harnesses

| Script | Tests |
|--------|-------|
| [`scripts/shard_router_test.py`](../scripts/shard_router_test.py) | Routing determinism + scatter-gather correctness. |
| [`scripts/sharded_ingest_test.py`](../scripts/sharded_ingest_test.py) | End-to-end sharded ingestion (writes through the router). |
| [`scripts/benchmark_sharding.py`](../scripts/benchmark_sharding.py) | The latency comparison above. |

Continue to [Caching](11-caching.md).
