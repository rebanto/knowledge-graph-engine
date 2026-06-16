import os
import chromadb
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

load_dotenv()

_client = None
_model = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        persist_dir = os.environ.get("CHROMA_PERSIST_DIR", "./chroma_data")
        _client = chromadb.PersistentClient(path=persist_dir)
    return _client


def get_collection(workspace_id: str):
    return get_client().get_or_create_collection(
        name=f"workspace_{workspace_id}_chunks",
        metadata={"hnsw:space": "cosine"},
    )


def add_chunks(workspace_id: str, chunks: list[dict]):
    """chunks: list of {id, text, metadata}"""
    if not chunks:
        return
    model = get_model()
    texts = [c["text"] for c in chunks]
    embeddings = model.encode(texts, show_progress_bar=False).tolist()
    get_collection(workspace_id).add(
        ids=[c["id"] for c in chunks],
        documents=texts,
        embeddings=embeddings,
        metadatas=[c["metadata"] for c in chunks],
    )


def embed_text(text: str) -> list[float]:
    return get_model().encode([text], show_progress_bar=False)[0].tolist()


def get_chunk_count(workspace_id: str) -> int:
    return get_collection(workspace_id).count()
