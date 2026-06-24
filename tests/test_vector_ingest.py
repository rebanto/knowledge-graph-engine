"""In-process ChromaDB tests (no server) for the vector ingest + retrieval path.

This is the deterministic regression for the reported symptom:
  "upload a short PDF, it says ready, but a question about it returns no info."

We embed a chunk that states a security code, then confirm a natural-language
question retrieves that exact chunk. Everything runs in a tmp persist dir, so
real workspace data is never touched. The embedding cache (Redis) is stubbed so
the test depends only on ChromaDB + the local embedding model.
"""
import importlib

import pytest

from tests.conftest import unique_ws

CODE = "Swordfish-Alpha-7723"
CHUNK_TEXT = f"Personal security note. My security code is {CODE}. Keep it private."


@pytest.fixture
def chroma(tmp_path, monkeypatch):
    """Fresh in-process ChromaDB rooted in a tmp dir."""
    # Force embedded mode: .env may set CHROMA_HOST (server mode) for the real
    # stack, but these tests must stay single-process in a throwaway tmp dir and
    # never touch the shared Chroma server.
    monkeypatch.delenv("CHROMA_HOST", raising=False)
    monkeypatch.delenv("CHROMA_PORT", raising=False)
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    import backend.db.chroma as chroma_mod
    importlib.reload(chroma_mod)  # re-read env, fresh client/global state
    # Stub the embedding cache so run_vector_query needs only Chroma + model.
    import backend.core.vector_retriever as vr
    importlib.reload(vr)
    monkeypatch.setattr(vr, "get_cached_embedding", lambda q: _async_none())
    monkeypatch.setattr(vr, "set_cached_embedding", lambda q, e: _async_none())
    yield chroma_mod, vr


async def _async_none():
    return None


def _chunk(ws, source_url, idx, text, source_id=""):
    return {
        "id": f"{ws}:{source_url}:{idx}",
        "text": text,
        "metadata": {
            "source_url": source_url,
            "source_title": "secret",
            "source_date": "",
            "chunk_index": idx,
            "workspace_id": ws,
            "source_id": source_id,
        },
    }


async def test_ingested_chunk_is_retrievable_by_question(chroma):
    chroma_mod, vr = chroma
    ws = unique_ws()
    url = "C:/uploads/secret.pdf"
    await chroma_mod.add_chunks(ws, [_chunk(ws, url, 0, CHUNK_TEXT)])

    assert await chroma_mod.get_chunk_count(ws) == 1

    result = await vr.run_vector_query("What is my security code?", ws, top_k=5)
    assert len(result["chunks"]) == 1
    assert CODE in result["chunks"][0]["text"]


async def test_empty_workspace_returns_no_chunks_without_crashing(chroma):
    chroma_mod, vr = chroma
    ws = unique_ws()
    result = await vr.run_vector_query("anything?", ws, top_k=5)
    assert result["chunks"] == []


async def test_has_chunks_for_source_matches_pdf_skip_key(chroma):
    chroma_mod, _ = chroma
    ws = unique_ws()
    url = "C:/uploads/secret.pdf"  # for a PDF, chunk_source == file path == source_url
    assert await chroma_mod.has_chunks_for_source(ws, url) is False
    await chroma_mod.add_chunks(ws, [_chunk(ws, url, 0, CHUNK_TEXT)])
    assert await chroma_mod.has_chunks_for_source(ws, url) is True


async def test_delete_by_source_url(chroma):
    chroma_mod, _ = chroma
    ws = unique_ws()
    url = "C:/uploads/secret.pdf"
    await chroma_mod.add_chunks(ws, [_chunk(ws, url, 0, CHUNK_TEXT)])
    await chroma_mod.delete_chunks_for_source(ws, url)
    assert await chroma_mod.get_chunk_count(ws) == 0


async def test_delete_by_source_id_purges_exactly_that_source(chroma):
    chroma_mod, _ = chroma
    ws = unique_ws()
    await chroma_mod.add_chunks(ws, [
        _chunk(ws, "u1", 0, "doc one " + CHUNK_TEXT, source_id="srcA"),
        _chunk(ws, "u2", 0, "doc two unrelated content", source_id="srcB"),
    ])
    assert await chroma_mod.get_chunk_count(ws) == 2

    await chroma_mod.delete_chunks_for_source_id(ws, "srcA")
    assert await chroma_mod.get_chunk_count(ws) == 1
    # the surviving chunk belongs to srcB
    remaining = await chroma_mod.get_all_source_urls(ws)
    assert remaining == {"u2"}


async def test_reingest_overwrites_not_duplicates(chroma):
    chroma_mod, _ = chroma
    ws = unique_ws()
    url = "C:/uploads/secret.pdf"
    # simulate the worker's _embed(): delete-then-upsert, twice
    for _ in range(2):
        await chroma_mod.delete_chunks_for_source(ws, url)
        await chroma_mod.add_chunks(ws, [_chunk(ws, url, 0, CHUNK_TEXT)])
    assert await chroma_mod.get_chunk_count(ws) == 1
