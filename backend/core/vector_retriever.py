from backend.db.chroma import embed_text, query_collection
from backend.db.redis import get_cached_embedding, set_cached_embedding
from backend.core.observability import cache_hits_total, cache_misses_total


async def run_vector_query(question: str, workspace_id: str, top_k: int = 5) -> dict:
    # L1+L2 embedding cache: same text always produces the same embedding
    cached_emb = await get_cached_embedding(question)
    if cached_emb is not None:
        cache_hits_total.labels(cache="embedding").inc()
        query_embedding = cached_emb
    else:
        cache_misses_total.labels(cache="embedding").inc()
        query_embedding = await embed_text(question)
        await set_cached_embedding(question, query_embedding)

    results = await query_collection(workspace_id, query_embedding, top_k)

    chunks = []
    documents = results.get("documents") or [[]]
    metadatas = results.get("metadatas") or [[]]
    distances = results.get("distances") or [[]]

    for text, metadata, distance in zip(documents[0], metadatas[0], distances[0]):
        chunks.append({
            "text": text,
            "source_title": metadata.get("source_title"),
            "source_url": metadata.get("source_url"),
            "distance": distance,
        })

    return {"chunks": chunks}
