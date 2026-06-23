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


def _has_chunks_for_source_sync(workspace_id: str, source_url: str) -> bool:
    if not source_url:
        return False
    got = _get_collection_sync(workspace_id).get(
        where={"source_url": source_url}, limit=1, include=[])
    return bool(got and got.get("ids"))


def _delete_chunks_for_source_sync(workspace_id: str, source_url: str):
    if not source_url:
        return
    # Remove every chunk previously written for this document so a re-ingest
    # replaces its chunk set rather than accumulating stale/duplicate chunks
    # (e.g. after the chunk-ID format changed or the document content shrank).
    _get_collection_sync(workspace_id).delete(where={"source_url": source_url})


def _delete_chunks_for_source_id_sync(workspace_id: str, source_id: str):
    if not source_id:
        return
    # Purge every chunk a given Postgres source contributed (used when a source
    # is deleted). Chunks are tagged with source_id at ingest time.
    _get_collection_sync(workspace_id).delete(where={"source_id": source_id})


def _delete_chunks_for_sources_sync(workspace_id: str, source_urls: list[str]) -> None:
    """Batch-delete chunks for multiple source URLs in one ChromaDB call."""
    if not source_urls:
        return
    col = _get_collection_sync(workspace_id)
    where = (
        {"source_url": source_urls[0]}
        if len(source_urls) == 1
        else {"source_url": {"$in": source_urls}}
    )
    try:
        col.delete(where=where)
    except Exception:
        # Fallback to individual deletes if the $in operator isn't supported
        for url in source_urls:
            try:
                col.delete(where={"source_url": url})
            except Exception:
                pass


def _get_all_source_urls_sync(workspace_id: str) -> set[str]:
    try:
        result = _get_collection_sync(workspace_id).get(include=["metadatas"])
        return {
            m["source_url"]
            for m in (result.get("metadatas") or [])
            if m and m.get("source_url")
        }
    except Exception:
        return set()


def _embed_text_sync(text: str) -> list[float]:
    return _get_model().encode([text], show_progress_bar=False)[0].tolist()


def _query_sync(workspace_id: str, embedding: list[float], top_k: int) -> dict:
    # Guard against an empty collection: ChromaDB raises if n_results exceeds the
    # number of stored vectors, so clamp to the count (and short-circuit when 0).
    col = _get_collection_sync(workspace_id)
    count = col.count()
    if count == 0:
        return {"documents": [[]], "metadatas": [[]], "distances": [[]]}
    return col.query(
        query_embeddings=[embedding],
        n_results=min(top_k, count),
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


async def has_chunks_for_source(workspace_id: str, source_url: str) -> bool:
    return await _run(_has_chunks_for_source_sync, workspace_id, source_url)


async def delete_chunks_for_source(workspace_id: str, source_url: str):
    await _run(_delete_chunks_for_source_sync, workspace_id, source_url)


async def delete_chunks_for_source_id(workspace_id: str, source_id: str):
    """Delete every chunk a deleted Postgres source contributed (by source_id)."""
    await _run(_delete_chunks_for_source_id_sync, workspace_id, source_id)


async def delete_chunks_for_sources(workspace_id: str, source_urls: list[str]) -> None:
    """Batch-delete chunks for multiple source URLs (workspace cleanup sweep)."""
    if source_urls:
        await _run(_delete_chunks_for_sources_sync, workspace_id, source_urls)


async def get_all_source_urls(workspace_id: str) -> set[str]:
    """Return all distinct source_url values stored in a workspace's collection."""
    return await _run(_get_all_source_urls_sync, workspace_id)


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
