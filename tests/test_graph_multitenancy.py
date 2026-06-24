"""Live Neo4j integration tests for workspace isolation + source deletion.

These pin the bug this change fixes: entity nodes were keyed by `name` alone
under a GLOBAL uniqueness constraint, so a Concept named "X" created by one
workspace was silently reused (and kept the first workspace's id) by every other
workspace. Effect: a workspace's own graph queries returned nothing, and
deleting a source could not detach that source's contribution.

After the fix, nodes are keyed by (name|arxiv_id, workspace_id), so each
workspace owns its own nodes and deletion is precise.

Auto-skips if Neo4j isn't reachable. Uses throwaway workspace ids and deletes
them in teardown, so real data is never touched.
"""
import pytest

from tests.conftest import unique_ws

pytestmark = pytest.mark.neo4j


@pytest.fixture(scope="session")
def neo4j_ready():
    from backend.db import neo4j as n
    try:
        d = n.get_driver()
        with d.session() as s:
            s.run("RETURN 1 AS ok").single()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Neo4j unavailable: {e}")
    n.setup_constraints()  # idempotent migration: composite (name, workspace_id)
    return n


class _Graph:
    def __init__(self, n):
        self.n = n
        self.workspaces: list[str] = []

    def ws(self, prefix="test_ws") -> str:
        w = unique_ws(prefix)
        self.workspaces.append(w)
        return w


@pytest.fixture
async def graph(neo4j_ready):
    g = _Graph(neo4j_ready)
    yield g
    # teardown: purge every node created under the test workspaces, then drop the
    # async driver so the next test re-creates it on its own event loop.
    d = await neo4j_ready.get_async_driver()
    async with d.session() as s:
        for w in g.workspaces:
            await s.run("MATCH (x {workspace_id: $ws}) DETACH DELETE x", ws=w)
    await neo4j_ready.close_async_driver()


async def _count(n, label, name, ws) -> int:
    d = await n.get_async_driver()
    async with d.session() as s:
        r = await s.run(
            f"MATCH (x:{label} {{name: $name, workspace_id: $ws}}) RETURN count(x) AS c",
            name=name, ws=ws,
        )
        return (await r.single())["c"]


async def _total(n, label, name) -> int:
    d = await n.get_async_driver()
    async with d.session() as s:
        r = await s.run(
            f"MATCH (x:{label} {{name: $name}}) RETURN count(x) AS c", name=name)
        return (await r.single())["c"]


async def _source_ids(n, label, name, ws):
    d = await n.get_async_driver()
    async with d.session() as s:
        r = await s.run(
            f"MATCH (x:{label} {{name: $name, workspace_id: $ws}}) "
            "RETURN x.source_ids AS sids",
            name=name, ws=ws,
        )
        rec = await r.single()
        return rec["sids"] if rec else None


# ── Isolation ──────────────────────────────────────────────────────────────────

async def test_same_named_concept_is_isolated_per_workspace(graph):
    n = graph.n
    a, b = graph.ws(), graph.ws()
    name = "KGRE_TransformerXYZ"

    await n.merge_node("Concept", name, a, source_id="srcA")
    await n.merge_node("Concept", name, b, source_id="srcB")

    # two physically distinct nodes — one per workspace
    assert await _total(n, "Concept", name) == 2
    # each workspace sees exactly its own (this returned 0 before the fix)
    assert await _count(n, "Concept", name, a) == 1
    assert await _count(n, "Concept", name, b) == 1
    # and each carries only its own source attribution
    assert await _source_ids(n, "Concept", name, a) == ["srcA"]
    assert await _source_ids(n, "Concept", name, b) == ["srcB"]


async def test_edges_do_not_bridge_workspaces(graph):
    n = graph.n
    a, b = graph.ws(), graph.ws()
    author, paper_title, paper_id_a, paper_id_b = "KGRE_Ada", "KGRE_Paper", "kgre_pa", "kgre_pb"

    for ws, pid in ((a, paper_id_a), (b, paper_id_b)):
        await n.merge_paper(pid, paper_title, ws, source_id=f"src_{ws}")
        await n.merge_node("Person", author, ws, source_id=f"src_{ws}")
        await n.merge_edge(author, "Person", pid, "Paper", "AUTHORED", ws,
                           {"source_document_id": pid}, source_id=f"src_{ws}")

    d = await n.get_async_driver()
    async with d.session() as s:
        # workspace A's author must connect ONLY to workspace A's paper
        r = await s.run(
            "MATCH (p:Person {name:$author, workspace_id:$ws})-[:AUTHORED]->(paper:Paper) "
            "RETURN collect(paper.workspace_id) AS wss",
            author=author, ws=a,
        )
        wss = (await r.single())["wss"]
    assert wss == [a], f"author edge leaked across workspaces: {wss}"


# ── Deletion precision ──────────────────────────────────────────────────────────

async def test_delete_source_keeps_node_shared_by_another_source(graph):
    n = graph.n
    a = graph.ws()
    name = "KGRE_SharedConcept"
    # two sources in the SAME workspace both assert the concept
    await n.merge_node("Concept", name, a, source_id="src1")
    await n.merge_node("Concept", name, a, source_id="src2")
    assert sorted(await _source_ids(n, "Concept", name, a)) == ["src1", "src2"]

    # removing src1 must NOT delete the node (src2 still references it)
    res = await n.remove_source_from_graph(a, "src1")
    assert res["nodes_removed"] == 0
    assert await _count(n, "Concept", name, a) == 1
    assert await _source_ids(n, "Concept", name, a) == ["src2"]

    # removing the last source deletes the now-orphaned node
    res2 = await n.remove_source_from_graph(a, "src2")
    assert res2["nodes_removed"] == 1
    assert await _count(n, "Concept", name, a) == 0


async def test_delete_source_does_not_touch_other_workspace(graph):
    n = graph.n
    a, b = graph.ws(), graph.ws()
    name = "KGRE_CrossWS"
    await n.merge_node("Concept", name, a, source_id="srcA")
    await n.merge_node("Concept", name, b, source_id="srcB")

    res = await n.remove_source_from_graph(a, "srcA")
    assert res["nodes_removed"] == 1
    # workspace A's node is gone; workspace B's identically-named node survives
    assert await _count(n, "Concept", name, a) == 0
    assert await _count(n, "Concept", name, b) == 1
    assert await _source_ids(n, "Concept", name, b) == ["srcB"]


async def test_delete_then_readd_recreates_node(graph):
    n = graph.n
    a = graph.ws()
    name = "KGRE_Recreate"
    await n.merge_node("Concept", name, a, source_id="srcA")
    await n.remove_source_from_graph(a, "srcA")
    assert await _count(n, "Concept", name, a) == 0

    # re-adding the same source (e.g. user re-uploads) must work, not silently skip
    await n.merge_node("Concept", name, a, source_id="srcA")
    assert await _count(n, "Concept", name, a) == 1


async def test_mark_paper_processed_is_workspace_scoped(graph):
    n = graph.n
    a, b = graph.ws(), graph.ws()
    pid = "kgre_shared_arxiv_id"
    await n.merge_paper(pid, "Shared Paper", a, source_id="srcA")
    await n.merge_paper(pid, "Shared Paper", b, source_id="srcB")

    await n.mark_paper_processed(pid, a)

    assert await n.is_paper_processed(pid, a) is True
    # the same arxiv_id in another workspace is independent
    assert await n.is_paper_processed(pid, b) is False
