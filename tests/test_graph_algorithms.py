"""Unit tests for the pure graph-algorithm compute functions (no DB/LLM)."""
from backend.core.graph_algorithms import (
    build_digraph,
    compute_pagerank,
    compute_communities,
)


def _edge(s, t, st="Concept", tt="Concept", conf=1.0):
    return {"source": s, "target": t, "source_type": st, "target_type": tt, "confidence": conf}


def test_build_digraph_accumulates_parallel_edge_weight():
    g = build_digraph([_edge("A", "B", conf=0.5), _edge("A", "B", conf=0.4)])
    assert g.has_edge("A", "B")
    assert g["A"]["B"]["weight"] == 0.9


def test_build_digraph_drops_self_loops_and_blanks():
    g = build_digraph([_edge("A", "A"), _edge("", "B"), _edge("C", "")])
    assert g.number_of_edges() == 0


def test_pagerank_ranks_hub_highest():
    # A star: everyone points at HUB, so HUB must have the top PageRank.
    edges = [_edge(n, "HUB") for n in ("A", "B", "C", "D")]
    ranked = compute_pagerank(edges)
    assert ranked[0]["name"] == "HUB"
    # Scores form a valid distribution (sum ~ 1.0; scores are rounded to 6dp).
    assert abs(sum(r["score"] for r in ranked) - 1.0) < 1e-3


def test_pagerank_carries_entity_type_and_respects_top_n():
    edges = [_edge(n, "HUB", st="Paper", tt="Person") for n in ("A", "B", "C")]
    ranked = compute_pagerank(edges, top_n=2)
    assert len(ranked) == 2
    assert ranked[0]["name"] == "HUB" and ranked[0]["type"] == "Person"


def test_pagerank_empty_graph_returns_empty():
    assert compute_pagerank([]) == []


def test_communities_separates_two_clusters():
    # Two triangles joined by a single bridge edge → two communities.
    cluster1 = [_edge("a1", "a2"), _edge("a2", "a3"), _edge("a3", "a1")]
    cluster2 = [_edge("b1", "b2"), _edge("b2", "b3"), _edge("b3", "b1")]
    bridge = [_edge("a1", "b1", conf=0.1)]
    comms = compute_communities(cluster1 + cluster2 + bridge)
    assert len(comms) == 2
    # Each cluster's three members land together.
    member_sets = [set(c["members"]) for c in comms]
    assert {"a1", "a2", "a3"} in member_sets
    assert {"b1", "b2", "b3"} in member_sets
    # community_id is assigned and sizes are reported.
    assert all("community_id" in c and c["size"] == 3 for c in comms)


def test_communities_drops_singletons():
    # One isolated edge pair only — min_size=2 keeps the pair, no singletons leak.
    comms = compute_communities([_edge("x", "y")], min_size=2)
    assert all(c["size"] >= 2 for c in comms)


def test_communities_empty_graph_returns_empty():
    assert compute_communities([]) == []
