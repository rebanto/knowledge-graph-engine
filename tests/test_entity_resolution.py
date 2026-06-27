"""Unit tests for three-band entity resolution (no model download, no LLM).

`_encode` is stubbed to return fixed 2-D unit vectors so cosine similarity is
exact and the band boundaries are deterministic; the LLM adjudicator is stubbed.
"""
import math
import numpy as np
import pytest

from backend.ingestion import entity_resolver as er
from backend.ingestion.entity_resolver import EntityResolver, band

# Unit vectors with known cosines against [1, 0]:
_V_SAME = np.array([1.0, 0.0])                                  # cos = 1.00 → merge
_V_BORDER = np.array([0.85, math.sqrt(1 - 0.85 ** 2)])         # cos = 0.85 → borderline
_V_DIFF = np.array([0.0, 1.0])                                  # cos = 0.00 → new


def _fake_encode(text: str) -> np.ndarray:
    if "SAME" in text:
        return _V_SAME
    if "BORDER" in text:
        return _V_BORDER
    return _V_DIFF


def _resolver(monkeypatch, adjudicate=True):
    monkeypatch.setattr(EntityResolver, "_encode", lambda self, text: _fake_encode(text))
    r = EntityResolver(adjudicate=adjudicate)
    # Seed one existing Concept whose embedding is [1, 0].
    r._registry["Concept"] = {"Existing": _V_SAME.copy()}
    return r


def test_band_boundaries():
    assert band(0.95, 0.82, 0.90) == "merge"
    assert band(0.90, 0.82, 0.90) == "merge"
    assert band(0.85, 0.82, 0.90) == "borderline"
    assert band(0.81, 0.82, 0.90) == "new"


@pytest.mark.asyncio
async def test_auto_merge_above_high(monkeypatch):
    r = _resolver(monkeypatch)
    out = await r.resolve_async("SAME thing", "Concept")
    assert out == "Existing"
    assert r.stats["auto_merge"] == 1


@pytest.mark.asyncio
async def test_new_below_low(monkeypatch):
    r = _resolver(monkeypatch)
    out = await r.resolve_async("DIFF thing", "Concept")
    assert out == "DIFF thing"
    assert r.stats["new"] == 1
    assert "DIFF thing" in r._registry["Concept"]


@pytest.mark.asyncio
async def test_borderline_adjudicated_merge(monkeypatch):
    r = _resolver(monkeypatch)

    async def _yes(a, b, t, ctx=""):
        return True
    monkeypatch.setattr(er, "_adjudicate_same", _yes)

    out = await r.resolve_async("BORDER thing", "Concept")
    assert out == "Existing"
    assert r.stats["adjudicated_merge"] == 1


@pytest.mark.asyncio
async def test_borderline_adjudicated_new(monkeypatch):
    r = _resolver(monkeypatch)

    async def _no(a, b, t, ctx=""):
        return False
    monkeypatch.setattr(er, "_adjudicate_same", _no)

    out = await r.resolve_async("BORDER thing", "Concept")
    assert out == "BORDER thing"
    assert r.stats["adjudicated_new"] == 1


@pytest.mark.asyncio
async def test_borderline_without_adjudication_is_new(monkeypatch):
    r = _resolver(monkeypatch, adjudicate=False)
    out = await r.resolve_async("BORDER thing", "Concept")
    assert out == "BORDER thing"


@pytest.mark.asyncio
async def test_first_entity_of_type_registers(monkeypatch):
    r = _resolver(monkeypatch)
    out = await r.resolve_async("SAME person", "Person")  # empty Person bucket
    assert out == "SAME person"
    assert r.stats["new"] == 1


@pytest.mark.asyncio
async def test_decide_pair_merge_and_distinct(monkeypatch):
    r = _resolver(monkeypatch)
    # Both encode to the same vector → cosine 1.0 → merge.
    assert await r.decide_pair("SAME a", "SAME b", "Concept") is True
    # Orthogonal vectors → cosine 0 → distinct.
    assert await r.decide_pair("SAME a", "DIFF b", "Concept") is False


@pytest.mark.asyncio
async def test_decide_pair_borderline_uses_adjudicator(monkeypatch):
    r = _resolver(monkeypatch)

    async def _yes(a, b, t, ctx=""):
        return True
    monkeypatch.setattr(er, "_adjudicate_same", _yes)
    # cos(SAME=[1,0], BORDER=[0.85,..]) = 0.85 → borderline → adjudicated True.
    assert await r.decide_pair("SAME a", "BORDER b", "Concept") is True
