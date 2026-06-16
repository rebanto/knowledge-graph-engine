from backend.db.chroma import get_collection, embed_text


def run_vector_query(question: str, workspace_id: str, top_k: int = 5) -> dict:
    collection = get_collection(workspace_id)
    query_embedding = embed_text(question)

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
    )

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
