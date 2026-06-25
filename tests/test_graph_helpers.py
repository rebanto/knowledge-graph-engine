"""Pure unit tests for graph-layer helpers — no services required.

Covers the entity-name extraction that scopes the degree/conflict passes and the
cross-shard row de-duplication key, both of which are easy to break silently.
"""
from backend.core.graph_retriever import _candidate_names, FORBIDDEN
from backend.db.shard_router import _row_key, shard_for


def test_candidate_names_filters_and_dedupes():
    rows = [
        {"name": "Geoffrey Hinton", "count": 3},
        {"name": "Geoffrey Hinton"},          # duplicate → collapsed
        {"url": "http://example.com/x"},        # urls excluded
        {"label": "AUTHORED"},                  # all-caps relation type excluded
        {"x": "ab"},                            # too short (<3 chars) excluded
        {"y": 42},                              # non-string excluded
        {"name": "Attention Is All You Need"},
    ]
    names = _candidate_names(rows)
    assert names == ["Geoffrey Hinton", "Attention Is All You Need"]


def test_candidate_names_caps_at_twenty():
    rows = [{"name": f"Entity Number {i}"} for i in range(40)]
    assert len(_candidate_names(rows)) == 20


def test_forbidden_rejects_writes_but_allows_reads():
    for bad in ["MATCH (n) CREATE (m)", "MERGE (a)", "MATCH (n) DELETE n",
                "MATCH (n) SET n.x = 1", "CALL db.labels()", "MATCH (n) DETACH DELETE n"]:
        assert FORBIDDEN.search(bad), f"should reject: {bad}"
    for ok in ["MATCH (n) RETURN n.name", "MATCH (a)-[r]->(b) RETURN type(r) LIMIT 10"]:
        assert not FORBIDDEN.search(ok), f"should allow: {ok}"


def test_row_key_is_order_independent():
    # Same row, keys in different insertion order → identical de-dupe key.
    assert _row_key({"a": 1, "b": 2}) == _row_key({"b": 2, "a": 1})
    assert _row_key({"a": 1}) != _row_key({"a": 2})


def test_shard_for_is_deterministic_and_in_range():
    for name in ["Transformer", "geoffrey hinton", "BERT", "x"]:
        s1 = shard_for(name, 3)
        s2 = shard_for(name.upper().lower(), 3)
        assert 0 <= s1 < 3
        assert s1 == s2, "shard assignment must be stable for the same name"
