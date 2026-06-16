import numpy as np
from sentence_transformers import SentenceTransformer

_model = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


class EntityResolver:
    """
    In-memory resolver: maps entity names to a canonical form using cosine
    similarity on sentence embeddings. Entities with similarity >= threshold
    are treated as the same entity and the first-seen name wins.
    """

    def __init__(self, threshold: float = 0.85):
        self.threshold = threshold
        # {entity_type -> {canonical_name -> embedding}}
        self._registry: dict[str, dict[str, np.ndarray]] = {}

    def resolve(self, name: str, entity_type: str) -> str:
        """Return canonical name, registering the entity if it is new."""
        if not name or not name.strip():
            return name

        model = _get_model()
        embedding = model.encode([name], show_progress_bar=False)[0]

        bucket = self._registry.setdefault(entity_type, {})

        if bucket:
            canonical_names = list(bucket.keys())
            matrix = np.array(list(bucket.values()))
            sims = self._cosine_sim(embedding, matrix)
            best = int(np.argmax(sims))
            if sims[best] >= self.threshold:
                return canonical_names[best]

        bucket[name] = embedding
        return name

    @staticmethod
    def _cosine_sim(vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
        v = vec / (np.linalg.norm(vec) + 1e-10)
        m = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-10)
        return m @ v
