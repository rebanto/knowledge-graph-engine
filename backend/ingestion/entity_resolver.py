import os
import numpy as np
from sentence_transformers import SentenceTransformer
from backend.db.redis import load_resolver_registry, flush_resolver_registry

_model = None

# Three-band resolution thresholds (cosine similarity of the embedded entity keys):
#   sim >= HIGH                → confidently the same entity, auto-merge
#   LOW <= sim < HIGH          → borderline, escalate to an LLM adjudicator
#   sim <  LOW                 → confidently distinct, register as new
#
# The bands are set by PRINCIPLE, not fitted to the eval pairs: the bi-encoder is
# a strong signal only at the extremes and a weak one in the middle, so we trust
# it alone only there and let the LLM arbitrate the wide ambiguous band.
#   * HIGH = 0.97 — auto-merge ONLY near-identical surface forms (case/whitespace
#     variants like "transformer"/"Transformer"). Versioned names such as
#     "GPT-4"/"GPT-4o" sit at ~0.95 yet are DIFFERENT entities, so anything below
#     0.97 must be confirmed, not auto-merged.
#   * LOW = 0.55 — below this the pair is almost certainly unrelated, so skip the
#     LLM call. Above it (but below HIGH) covers the cases embeddings get wrong in
#     both directions: acronym↔expansion pairs ("LSTM"/"Long Short-Term Memory"
#     score ~0.59, "CNN"/"Convolutional Neural Network" ~0.76) that should merge
#     but score low, AND near-synonyms ("attention"/"self-attention" ~0.84) that
#     should NOT. A cheap LLM yes/no resolves both far better than any fixed cut.
# Trade-off: a lower LOW sends more borderline pairs to the LLM during ingestion
# (extra calls); ENTITY_RESOLVE_ADJUDICATE=false disables that and treats the
# whole borderline band as non-matches.
_HIGH = float(os.environ.get("ENTITY_RESOLVE_HIGH", 0.97))
_LOW = float(os.environ.get("ENTITY_RESOLVE_LOW", 0.55))
_ADJUDICATE = os.environ.get("ENTITY_RESOLVE_ADJUDICATE", "true").lower() in ("1", "true", "yes")


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def _embed_input(name: str, entity_type: str, aliases: list[str] | None = None) -> str:
    """The string actually embedded for matching.

    Including the type disambiguates same-spelling/different-kind collisions
    (the model "BERT" vs the person "Bert"); folding in aliases pulls known
    surface forms of one entity closer together.
    """
    parts = [name.strip(), f"type: {entity_type}"]
    if aliases:
        parts.append("aka " + ", ".join(a for a in aliases if a))
    return " | ".join(parts)


def band(sim: float, low: float = _LOW, high: float = _HIGH) -> str:
    """Pure classification of a similarity score into merge/borderline/new."""
    if sim >= high:
        return "merge"
    if sim < low:
        return "new"
    return "borderline"


class EntityResolver:
    """
    Cross-source entity deduplication using sentence-embedding cosine similarity
    with a three-band decision and optional LLM adjudication for borderline pairs.

    Registry is seeded from Redis at job start (load_from_redis) and flushed back
    at job end (flush_to_redis), so dedup works across multiple sources and across
    worker restarts.

    `threshold` keeps the original single-band behaviour for the synchronous
    `resolve()` (used by the LLM-free author path and the seed script). The richer
    three-band `resolve_async()` is used for LLM-extracted entities, which are the
    ones that actually collide.
    """

    def __init__(
        self, threshold: float = 0.85,
        low: float = _LOW, high: float = _HIGH, adjudicate: bool = _ADJUDICATE,
    ):
        self.threshold = threshold
        self.low = low
        self.high = high
        self.adjudicate = adjudicate
        self._registry: dict[str, dict[str, np.ndarray]] = {}
        # Decision counters — exposed for the eval harness / dashboards.
        self.stats = {"auto_merge": 0, "new": 0, "adjudicated_merge": 0, "adjudicated_new": 0}

    async def load_from_redis(self, workspace_id: str) -> None:
        """Populate registry from Redis before processing a source."""
        for entity_type in ("Person", "Organization", "Paper", "Concept", "Event", "Topic"):
            bucket = await load_resolver_registry(workspace_id, entity_type)
            if bucket:
                self._registry[entity_type] = bucket

    async def flush_to_redis(self, workspace_id: str) -> None:
        """Persist updated registry back to Redis after processing a source."""
        for entity_type, bucket in self._registry.items():
            await flush_resolver_registry(workspace_id, entity_type, bucket)

    def _encode(self, text: str) -> np.ndarray:
        return _get_model().encode([text], show_progress_bar=False)[0]

    def _best_match(self, name: str, entity_type: str, aliases=None):
        """Return (embedding, bucket, best_name, best_sim) for the closest existing
        entity of the same type. best_name is None when the bucket is empty."""
        embedding = self._encode(_embed_input(name, entity_type, aliases))
        bucket = self._registry.setdefault(entity_type, {})
        if not bucket:
            return embedding, bucket, None, 0.0
        canonical_names = list(bucket.keys())
        matrix = np.array(list(bucket.values()))
        sims = _cosine_sim(embedding, matrix)
        best = int(np.argmax(sims))
        return embedding, bucket, canonical_names[best], float(sims[best])

    def resolve(self, name: str, entity_type: str, aliases=None) -> str:
        """Synchronous, single-threshold resolution (backward compatible).

        Returns the canonical name, registering the entity if new. Used where an
        LLM call is unwarranted (structured author names, the offline seed script).
        """
        if not name or not name.strip():
            return name
        embedding, bucket, best_name, best_sim = self._best_match(name, entity_type, aliases)
        if best_name is not None and best_sim >= self.threshold:
            self.stats["auto_merge"] += 1
            return best_name
        bucket[name] = embedding
        self.stats["new"] += 1
        return name

    async def resolve_async(self, name: str, entity_type: str, aliases=None, context: str = "") -> str:
        """Three-band resolution with LLM adjudication for the borderline band.

        Used for LLM-extracted entities (the ones that genuinely collide). Above
        HIGH auto-merges; below LOW registers new; in between, asks the LLM whether
        the two names denote the same entity (when adjudication is enabled).
        """
        if not name or not name.strip():
            return name
        embedding, bucket, best_name, best_sim = self._best_match(name, entity_type, aliases)
        if best_name is None:
            bucket[name] = embedding
            self.stats["new"] += 1
            return name

        decision = band(best_sim, self.low, self.high)
        if decision == "merge":
            self.stats["auto_merge"] += 1
            return best_name
        if decision == "borderline" and self.adjudicate:
            same = await _adjudicate_same(best_name, name, entity_type, context)
            if same:
                self.stats["adjudicated_merge"] += 1
                return best_name
            self.stats["adjudicated_new"] += 1

        bucket[name] = embedding
        if decision != "borderline":
            self.stats["new"] += 1
        return name


    async def decide_pair(self, a: str, b: str, entity_type: str, context: str = "") -> bool:
        """Registry-independent merge decision for two names (same banding +
        adjudication as resolve_async). Used by the eval harness to measure
        resolution precision/recall against labeled pairs."""
        ea = self._encode(_embed_input(a, entity_type))
        eb = self._encode(_embed_input(b, entity_type))
        sim = float(_cosine_sim(ea, eb.reshape(1, -1))[0])
        decision = band(sim, self.low, self.high)
        if decision == "merge":
            return True
        if decision == "new":
            return False
        if self.adjudicate:
            return await _adjudicate_same(a, b, entity_type, context)
        return False


_ADJUDICATION_PROMPT = """Do these two names refer to the SAME real-world {entity_type}?

Name A: "{a}"
Name B: "{b}"
{context}
Consider abbreviations, aliases, and spelling variants, but DO NOT merge two
genuinely different entities that merely sound similar (e.g. different versions,
different people sharing a surname).

Return ONLY JSON: {{"same": true|false}}"""


async def _adjudicate_same(a: str, b: str, entity_type: str, context: str = "") -> bool:
    """LLM yes/no on whether two entity names denote the same entity.

    Imported lazily so the resolver module has no hard dependency on the LLM
    client (keeps the sync path and unit tests free of it). Fails closed (no
    merge) on any error, which is the safe default — a missed merge leaves a
    duplicate; a wrong merge silently corrupts the graph.
    """
    try:
        from backend.core.llm_client import generate_json
        ctx = f'Context: {context.strip()}\n' if context and context.strip() else ""
        data = await generate_json(
            _ADJUDICATION_PROMPT.format(entity_type=entity_type, a=a, b=b, context=ctx)
        )
        return bool(data.get("same") is True)
    except Exception:
        return False


def _cosine_sim(vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    v = vec / (np.linalg.norm(vec) + 1e-10)
    m = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-10)
    return m @ v
