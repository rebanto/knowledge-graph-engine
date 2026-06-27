"""Unit tests for the text-to-Cypher self-correction loop (no DB/LLM).

`_exec` and the LLM regeneration call are stubbed, so these exercise the control
flow: passthrough on success, syntax repair, empty-result reformulation, and
giving up after the attempt budget.
"""
import pytest
from neo4j.exceptions import ClientError

from backend.core import graph_retriever as gr

GOOD = "MATCH (n {workspace_id: 'w'}) RETURN n.name AS name"
REPAIRED = "MATCH (n {workspace_id: 'w'}) RETURN n.name AS name LIMIT 10"


def _seq_exec(behaviors):
    """Build an async _exec stub that consumes `behaviors` one call at a time.
    Each behavior is either an Exception (raised) or a list (returned)."""
    calls = {"n": 0}

    async def _exec(cypher, params=None, timeout=15):
        b = behaviors[calls["n"]]
        calls["n"] += 1
        if isinstance(b, Exception):
            raise b
        return b

    _exec.calls = calls
    return _exec


def _const_regen(cypher):
    async def _regen(prompt_template, **fields):
        return cypher
    return _regen


@pytest.mark.asyncio
async def test_passthrough_on_success(monkeypatch):
    monkeypatch.setattr(gr, "_exec", _seq_exec([[{"name": "A"}]]))
    # If regeneration is called, fail loudly — it must not be on the happy path.
    async def _boom(*a, **k):
        raise AssertionError("should not regenerate on success")
    monkeypatch.setattr(gr, "_regenerate_cypher", _boom)

    cypher, records = await gr._execute_with_repair("q", "w", GOOD)
    assert cypher == GOOD
    assert records == [{"name": "A"}]


@pytest.mark.asyncio
async def test_syntax_error_is_repaired(monkeypatch):
    monkeypatch.setattr(
        gr, "_exec",
        _seq_exec([ClientError("SyntaxError: bad"), [{"name": "A"}]]),
    )
    monkeypatch.setattr(gr, "_regenerate_cypher", _const_regen(REPAIRED))

    cypher, records = await gr._execute_with_repair("q", "w", GOOD)
    assert cypher == REPAIRED          # adopted the repaired query
    assert records == [{"name": "A"}]


@pytest.mark.asyncio
async def test_gives_up_after_budget(monkeypatch):
    # Every attempt errors; after MAX_CYPHER_ATTEMPTS the last error propagates.
    errs = [ClientError(f"err{i}") for i in range(gr.MAX_CYPHER_ATTEMPTS)]
    monkeypatch.setattr(gr, "_exec", _seq_exec(errs))
    monkeypatch.setattr(gr, "_regenerate_cypher", _const_regen(REPAIRED))

    with pytest.raises(ClientError):
        await gr._execute_with_repair("q", "w", GOOD)


@pytest.mark.asyncio
async def test_empty_result_triggers_one_reformulation(monkeypatch):
    # First query is valid but empty → reformulate once → second query has rows.
    monkeypatch.setattr(gr, "_exec", _seq_exec([[], [{"name": "A"}]]))
    monkeypatch.setattr(gr, "_regenerate_cypher", _const_regen(REPAIRED))

    cypher, records = await gr._execute_with_repair("q", "w", GOOD)
    assert cypher == REPAIRED
    assert records == [{"name": "A"}]


@pytest.mark.asyncio
async def test_persistent_empty_returns_empty_not_error(monkeypatch):
    # Empty, reformulate, still empty → return empty (only one reformulation).
    ex = _seq_exec([[], []])
    monkeypatch.setattr(gr, "_exec", ex)
    monkeypatch.setattr(gr, "_regenerate_cypher", _const_regen(REPAIRED))

    cypher, records = await gr._execute_with_repair("q", "w", GOOD)
    assert records == []
    assert ex.calls["n"] == 2  # original + exactly one reformulation
