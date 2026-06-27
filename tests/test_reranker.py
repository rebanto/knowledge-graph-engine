"""Unit tests for the cross-encoder reranker control flow (no model download).

The pure ordering function is tested directly; the async path is tested with the
model stubbed out via monkeypatch, so no weights are loaded.
"""
import pytest

from backend.core import reranker


def _chunks(*texts):
    return [{"text": t, "source_url": f"u/{t}"} for t in texts]


def test_rerank_by_scores_reorders_and_truncates():
    chunks = _chunks("a", "b", "c")
    # b is most relevant, then c, then a.
    out = reranker.rerank_by_scores(chunks, [0.1, 0.9, 0.5], top_k=2)
    assert [c["text"] for c in out] == ["b", "c"]
    assert out[0]["rerank_score"] == 0.9
    assert "source_url" in out[0]  # original fields preserved


def test_rerank_by_scores_is_stable_on_ties():
    chunks = _chunks("a", "b", "c")
    out = reranker.rerank_by_scores(chunks, [0.5, 0.5, 0.5], top_k=3)
    assert [c["text"] for c in out] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_rerank_passthrough_when_disabled(monkeypatch):
    monkeypatch.setattr(reranker, "is_enabled", lambda: False)
    chunks = _chunks("a", "b", "c", "d")
    out = await reranker.rerank("q", chunks, top_k=2)
    assert [c["text"] for c in out] == ["a", "b"]  # original order, truncated


@pytest.mark.asyncio
async def test_rerank_falls_back_when_model_unavailable(monkeypatch):
    monkeypatch.setattr(reranker, "is_enabled", lambda: True)
    monkeypatch.setattr(reranker, "_get_model", lambda: None)  # load "failed"
    chunks = _chunks("a", "b", "c")
    out = await reranker.rerank("q", chunks, top_k=2)
    assert [c["text"] for c in out] == ["a", "b"]


@pytest.mark.asyncio
async def test_rerank_uses_scores_when_model_present(monkeypatch):
    monkeypatch.setattr(reranker, "is_enabled", lambda: True)
    monkeypatch.setattr(reranker, "_get_model", lambda: object())  # non-None
    # Stub the synchronous scorer: reverse-relevance so order flips.
    monkeypatch.setattr(reranker, "_score_sync", lambda q, texts: [0.1, 0.2, 0.9])
    out = await reranker.rerank("q", _chunks("a", "b", "c"), top_k=2)
    assert [c["text"] for c in out] == ["c", "b"]
