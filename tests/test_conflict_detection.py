"""Live Neo4j integration tests for the Phase 6 conflict-detection read pass.

Ingestion flags contradictions in the graph (conflict_flag=true on the opposing
SUPPORTS/CONTRADICTS edges, plus a CONFLICTS_WITH edge), but query time never
read them back. graph_retriever._detect_conflicts() now surfaces the flagged
pairs that involve the answer's entities. These tests seed a contradiction
directly and assert it comes back — and that an undisputed edge does not.

Auto-skips if Neo4j is unreachable. Uses throwaway workspace ids cleaned up in
teardown.
"""
import pytest

from tests.conftest import unique_ws

pytestmark = pytest.mark.neo4j


@pytest.fixture
async def neo():
    from backend.db import neo4j as n
    from backend.db import shard_router
    # Module-global Neo4j drivers (single-node and the shard router) bind their
    # pools to whichever event loop first used them; pytest-asyncio gives each
    # test a fresh loop. Drop stale bindings up front so reads in _detect_conflicts
    # (which under USE_SHARDING go through the shard router) don't silently error
    # out on a dead loop and get swallowed to an empty result.
    await n.close_async_driver()
    await shard_router.close_router()
    try:
        d = await n.get_async_driver()
        async with d.session() as s:
            await (await s.run("RETURN 1 AS ok")).single()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Neo4j unavailable: {e}")

    workspaces: list[str] = []
    yield n, workspaces

    d = await n.get_async_driver()
    async with d.session() as s:
        for w in workspaces:
            await s.run("MATCH (x {workspace_id:$ws}) DETACH DELETE x", ws=w)
    await n.close_async_driver()
    await shard_router.close_router()


async def _seed_disputed_pair(n, ws, a, b):
    """Two sources make opposite claims about (a, b): one SUPPORTS, one
    CONTRADICTS — exactly what conflict_detector flags during ingestion."""
    await n.merge_node("Concept", a, ws, source_id="src1")
    await n.merge_node("Concept", b, ws, source_id="src2")
    await n.merge_edge(a, "Concept", b, "Concept", "SUPPORTS", ws,
                       {"source_document_id": "doc_pro", "conflict_flag": True},
                       source_id="src1")
    await n.merge_edge(a, "Concept", b, "Concept", "CONTRADICTS", ws,
                       {"source_document_id": "doc_con", "conflict_flag": True},
                       source_id="src2")


async def test_detect_conflicts_surfaces_disputed_pair(neo):
    from backend.core.graph_retriever import _detect_conflicts
    n, workspaces = neo
    ws = unique_ws("conflict")
    workspaces.append(ws)
    a, b = "KGRE_ClaimA", "KGRE_ClaimB"
    await _seed_disputed_pair(n, ws, a, b)

    conflicts = await _detect_conflicts(ws, [a, b])
    assert len(conflicts) == 1, f"expected one disputed pair, got {conflicts}"
    c = conflicts[0]
    assert {c["source"], c["target"]} == {a, b}
    assert set(c["claim_types"]) == {"SUPPORTS", "CONTRADICTS"}
    assert set(c["documents"]) == {"doc_pro", "doc_con"}


async def test_detect_conflicts_dedupes_undirected_pair(neo):
    """Passing both endpoints must still yield the pair once, not twice."""
    from backend.core.graph_retriever import _detect_conflicts
    n, workspaces = neo
    ws = unique_ws("conflict")
    workspaces.append(ws)
    a, b = "KGRE_DupA", "KGRE_DupB"
    await _seed_disputed_pair(n, ws, a, b)

    conflicts = await _detect_conflicts(ws, [a, b, a])
    assert len(conflicts) == 1


async def test_undisputed_edge_is_not_flagged(neo):
    """A normal SUPPORTS edge with no conflict_flag must not be reported."""
    from backend.core.graph_retriever import _detect_conflicts
    n, workspaces = neo
    ws = unique_ws("conflict")
    workspaces.append(ws)
    a, b = "KGRE_CalmA", "KGRE_CalmB"
    await n.merge_node("Concept", a, ws, source_id="src1")
    await n.merge_node("Concept", b, ws, source_id="src1")
    await n.merge_edge(a, "Concept", b, "Concept", "SUPPORTS", ws,
                       {"source_document_id": "doc1"}, source_id="src1")

    conflicts = await _detect_conflicts(ws, [a, b])
    assert conflicts == []


async def test_detect_conflicts_empty_names_is_noop(neo):
    from backend.core.graph_retriever import _detect_conflicts
    _, _ = neo
    assert await _detect_conflicts("any_ws", []) == []
