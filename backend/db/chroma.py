import os
import asyncio
from concurrent.futures import ThreadPoolExecutor
import chromadb
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

load_dotenv()

_client = None
_model = None
# Dedicated thread pool for ChromaDB — it has no async API.
# Isolating it here prevents slow Chroma I/O from blocking the DB thread pool.
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="chroma")


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def _get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        persist_dir = os.environ.get("CHROMA_PERSIST_DIR", "./chroma_data")
        _client = chromadb.PersistentClient(path=persist_dir)
    return _client


def _get_collection_sync(workspace_id: str):
    return _get_client().get_or_create_collection(
        name=f"workspace_{workspace_id}_chunks",
        metadata={"hnsw:space": "cosine"},
    )


def _add_chunks_sync(workspace_id: str, chunks: list[dict]):
    if not chunks:
        return
    model = _get_model()
    texts = [c["text"] for c in chunks]
    embeddings = model.encode(texts, show_progress_bar=False).tolist()
    # upsert (not add) so re-ingesting a document — e.g. after a worker
    # reassignment in Phase 3 — is a no-op rather than a duplicate-ID crash.
    _get_collection_sync(workspace_id).upsert(
        ids=[c["id"] for c in chunks],
        documents=texts,
        embeddings=embeddings,
        metadatas=[c["metadata"] for c in chunks],
    )


def _delete_chunks_for_source_sync(workspace_id: str, source_url: str):
    if not source_url:
        return
    # Remove every chunk previously written for this document so a re-ingest
    # replaces its chunk set rather than accumulating stale/duplicate chunks
    # (e.g. after the chunk-ID format changed or the document content shrank).
    _get_collection_sync(workspace_id).delete(where={"source_url": source_url})


def _embed_text_sync(text: str) -> list[float]:
    return _get_model().encode([text], show_progress_bar=False)[0].tolist()


def _query_sync(workspace_id: str, embedding: list[float], top_k: int) -> dict:
    return _get_collection_sync(workspace_id).query(
        query_embeddings=[embedding],
        n_results=top_k,
    )


def _count_sync(workspace_id: str) -> int:
    return _get_collection_sync(workspace_id).count()


# ── Async wrappers ─────────────────────────────────────────────────────────────

def _run(fn, *args):
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(_executor, fn, *args)


async def get_collection(workspace_id: str):
    return await _run(_get_collection_sync, workspace_id)


async def add_chunks(workspace_id: str, chunks: list[dict]):
    await _run(_add_chunks_sync, workspace_id, chunks)


async def delete_chunks_for_source(workspace_id: str, source_url: str):
    await _run(_delete_chunks_for_source_sync, workspace_id, source_url)


async def embed_text(text: str) -> list[float]:
    return await _run(_embed_text_sync, text)


async def query_collection(workspace_id: str, embedding: list[float], top_k: int) -> dict:
    return await _run(_query_sync, workspace_id, embedding, top_k)


async def get_chunk_count(workspace_id: str) -> int:
    return await _run(_count_sync, workspace_id)


# Sync versions kept for the seed script
def add_chunks_sync(workspace_id: str, chunks: list[dict]):
    _add_chunks_sync(workspace_id, chunks)


def embed_text_sync(text: str) -> list[float]:
    return _embed_text_sync(text)
