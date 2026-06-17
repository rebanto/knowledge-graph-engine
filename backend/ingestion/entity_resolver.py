import numpy as np
from sentence_transformers import SentenceTransformer
from backend.db.redis import load_resolver_registry, flush_resolver_registry

_model = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


class EntityResolver:
    """
    Cross-source entity deduplication using sentence-embedding cosine similarity.

    Registry is seeded from Redis at job start (load_from_redis) and flushed
    back at job end (flush_to_redis), so dedup works across multiple sources
    and across worker restarts.
    """

    def __init__(self, threshold: float = 0.85):
        self.threshold = threshold
        self._registry: dict[str, dict[str, np.ndarray]] = {}

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

    def resolve(self, name: str, entity_type: str) -> str:
        """Return canonical name, registering the entity if new."""
        if not name or not name.strip():
            return name

        model = _get_model()
        embedding = model.encode([name], show_progress_bar=False)[0]

        bucket = self._registry.setdefault(entity_type, {})

        if bucket:
            canonical_names = list(bucket.keys())
            matrix = np.array(list(bucket.values()))
            sims = _cosine_sim(embedding, matrix)
            best = int(np.argmax(sims))
            if sims[best] >= self.threshold:
                return canonical_names[best]

        bucket[name] = embedding
        return name


def _cosine_sim(vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    v = vec / (np.linalg.norm(vec) + 1e-10)
    m = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-10)
    return m @ v
