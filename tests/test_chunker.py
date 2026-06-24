"""Unit tests for the document chunker.

Regression focus: a short document must still produce a (single, non-empty)
chunk. If the chunker ever returned [] for short text, that document would be
ingested, marked 'success', yet hold zero searchable chunks — the exact
"source is ready but a question about it returns no information" symptom.
"""
from backend.ingestion.chunker import chunk_text


def test_short_text_yields_one_nonempty_chunk():
    text = "My security code is Swordfish-Alpha-7723."
    chunks = chunk_text(text)
    assert chunks == [text]
    assert all(c.strip() for c in chunks)


def test_single_word_is_kept():
    assert chunk_text("hello") == ["hello"]


def test_long_text_splits_with_overlap():
    words = [f"w{i}" for i in range(1000)]
    text = " ".join(words)
    chunks = chunk_text(text, chunk_size=400, overlap=40)

    # multiple chunks, each within the size bound
    assert len(chunks) > 1
    for c in chunks:
        assert len(c.split()) <= 400

    # consecutive chunks overlap (last 40 words of one ~= first 40 of the next)
    first_tail = chunks[0].split()[-40:]
    second_head = chunks[1].split()[:40]
    assert first_tail == second_head


def test_full_coverage_no_words_lost():
    words = [f"w{i}" for i in range(950)]
    text = " ".join(words)
    chunks = chunk_text(text, chunk_size=400, overlap=40)
    seen = set()
    for c in chunks:
        seen.update(c.split())
    assert seen == set(words)
