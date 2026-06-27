"""
Cross-encoder reranking for the vector retrieval path.

The bi-encoder used for retrieval (all-MiniLM, in chroma.py) embeds the query and
each chunk independently, so its ranking is a coarse cosine-similarity proxy. A
cross-encoder reads the (query, chunk) PAIR jointly and scores relevance directly
— far more accurate, but too slow to run over a whole collection. The standard
two-stage pattern, and what this implements:

    retrieve top-N cheaply (bi-encoder) → rerank N → keep top-k (cross-encoder)

Design choices:
  * Opt-in via USE_RERANKER (default on) and degrades gracefully — if the model
    can't load (offline, missing weights), retrieval falls back to the bi-encoder
    order rather than failing the query.
  * The model runs in its own thread pool (predict() is sync, CPU-bound) so it
    can't block the event loop or starve the DB/LLM pools.
  * `rerank_by_scores` is pure (scores injected) so the ordering logic unit-tests
    without downloading a model.
"""
import os
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

_MODEL_NAME = os.environ.get("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
# How many candidates to pull from the vector store before reranking, as a
# multiple of the final top_k. 3× gives the cross-encoder room to reorder without
# embedding the whole collection.
FETCH_MULTIPLIER = int(os.environ.get("RERANK_FETCH_MULTIPLIER", 3))

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rerank")
_model = None
_load_failed = False


def is_enabled() -> bool:
    return os.environ.get("USE_RERANKER", "true").lower() in ("1", "true", "yes")


def _get_model():
    """Lazy-load the CrossEncoder. On failure, remember it and return None so the
    caller degrades to the bi-encoder ordering instead of retrying every query."""
    global _model, _load_failed
    if _model is not None or _load_failed:
        return _model
    try:
        from sentence_transformers import CrossEncoder
        _model = CrossEncoder(_MODEL_NAME)
    except Exception as e:  # missing weights, offline, OOM…
        logger.warning("reranker disabled — model load failed: %s", e)
        _load_failed = True
    return _model


def rerank_by_scores(chunks: list[dict], scores: list[float], top_k: int) -> list[dict]:
    """Pure: attach `rerank_score`, sort by it desc, return the top_k.

    Stable for equal scores (Python sort is stable and we pre-pair in order), so
    ties keep their original bi-encoder order."""
    paired = list(zip(chunks, scores))
    paired.sort(key=lambda cs: cs[1], reverse=True)
    out = []
    for chunk, score in paired[:top_k]:
        out.append({**chunk, "rerank_score": float(score)})
    return out


def _score_sync(query: str, texts: list[str]) -> list[float]:
    model = _get_model()
    if model is None:
        return []
    scores = model.predict([(query, t) for t in texts])
    return [float(s) for s in scores]


async def rerank(query: str, chunks: list[dict], top_k: int) -> list[dict]:
    """Rerank retrieved chunks with the cross-encoder, returning the top_k.

    Falls back to `chunks[:top_k]` (bi-encoder order) when reranking is disabled,
    the model can't load, or there is nothing to reorder.
    """
    if not is_enabled() or len(chunks) <= 1:
        return chunks[:top_k]
    if _get_model() is None:
        return chunks[:top_k]

    loop = asyncio.get_event_loop()
    texts = [c.get("text", "") for c in chunks]
    scores = await loop.run_in_executor(_executor, _score_sync, query, texts)
    if not scores or len(scores) != len(chunks):
        return chunks[:top_k]  # scoring failed mid-flight — keep original order
    return rerank_by_scores(chunks, scores, top_k)
