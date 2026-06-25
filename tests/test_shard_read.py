"""Live integration tests for the Phase 4 sharded read path.

Pins the gap this change closes: writes were sharded but reads were not — under
USE_SHARDING graph_retriever still hit a single node, so a query only ever saw
shard 0's slice. ShardRouter.run_read() now scatter-gathers the same Cypher
across every shard and unions the rows; entity_degree_context() sums per-entity
degree across shards without double counting.

Auto-skips unless all NUM_SHARDS Neo4j instances are reachable (bolt
7687/7688/7689 in local dev). Uses a throwaway workspace id and deletes it in
teardown, so real data is never touched.
"""
import pytest

from tests.conftest import unique_ws

pytestmark = pytest.mark.neo4j


@pytest.fixture
async def router():
    from backend.db.shard_router import ShardRouter
    try:
        r = ShardRouter()
        # Probe every shard; skip the whole module if any is unreachable.
        for i in range(r.n):
            async with r._drivers[i].session() as s:
                await (await s.run("RETURN 1 AS ok")).single()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Sharded Neo4j unavailable: {e}")

    created: list[str] = []
    r._test_workspaces = created  # type: ignore[attr-defined]
    yield r
    for ws in created:
        for d in r._drivers:
            async with d.session() as s:
                await s.run("MATCH (x {workspace_id:$ws}) DETACH DELETE x", ws=ws)
    await r.close()


def _ws(router) -> str:
    w = unique_ws("shard_read")
    router._test_workspaces.append(w)
    return w


async def test_run_read_unions_rows_from_every_shard(router):
    """Three concepts that hash to (potentially) different shards must all come
    back from one workspace-scoped run_read — not just the ones on shard 0."""
    ws = _ws(router)
    names = [f"KGRE_Read_{i}" for i in range(12)]
    for nm in names:
        await router.merge_node("Concept", nm, ws)

    # Sanity: the names really do spread across more than one shard, otherwise the
    # union isn't being exercised.
    shards_hit = {router.shard_for(nm) for nm in names}
    assert len(shards_hit) > 1, "test names did not spread across shards"

    rows = await router.run_read(
        "MATCH (n:Concept {workspace_id: $ws}) RETURN n.name AS name",
        {"ws": ws},
    )
    got = {r["name"] for r in rows}
    assert got == set(names), f"union missed nodes off shard 0: {set(names) - got}"


async def test_run_read_dedupes_cross_shard_stub(router):
    """A cross-shard edge leaves a stub of the target on the source shard. A query
    that returns that target by name must yield it once, not once per shard."""
    ws = _ws(router)
    # Find A and B on different shards sharing a neighbour Z.
    a = next(nm for nm in (f"RA {k}" for k in range(500)) if router.shard_for(nm) == 0)
    b = next(nm for nm in (f"RB {k}" for k in range(500)) if router.shard_for(nm) == 1)
    z = "KGRE_Read_SharedZ"
    for nm in (a, b, z):
        await router.merge_node("Concept", nm, ws)
    await router.merge_edge(a, "Concept", z, "Concept", "SUPPORTS", ws, {"confidence": 0.9})
    await router.merge_edge(b, "Concept", z, "Concept", "SUPPORTS", ws, {"confidence": 0.9})

    rows = await router.run_read(
        "MATCH (n:Concept {name: $z, workspace_id: $ws}) RETURN n.name AS name",
        {"z": z, "ws": ws},
    )
    assert [r["name"] for r in rows] == [z], f"stub not de-duped across shards: {rows}"


async def test_entity_degree_context_sums_across_shards(router):
    """Z is the target of two cross-shard SUPPORTS edges whose physical copies
    live on different shards. Its degree must be the SUM (2), proving the read
    didn't just look at Z's owning shard."""
    ws = _ws(router)
    a = next(nm for nm in (f"DA {k}" for k in range(500)) if router.shard_for(nm) == 0)
    b = next(nm for nm in (f"DB {k}" for k in range(500)) if router.shard_for(nm) == 1)
    z = "KGRE_Degree_Z"
    for nm in (a, b, z):
        await router.merge_node("Concept", nm, ws)
    await router.merge_edge(a, "Concept", z, "Concept", "SUPPORTS", ws)
    await router.merge_edge(b, "Concept", z, "Concept", "SUPPORTS", ws)

    ctx = await router.entity_degree_context(ws, [z])
    by_name = {r["name"]: r["degree"] for r in ctx}
    assert by_name.get(z) == 2, f"degree not summed across shards: {ctx}"
