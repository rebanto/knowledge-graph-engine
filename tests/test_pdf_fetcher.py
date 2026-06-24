"""Unit tests for the PDF fetcher.

Covers the reported flow's first step: a short uploaded PDF must yield a document
whose text contains the PDF's content, with a deterministic id/url so the
downstream chunk ids and idempotency skip line up.
"""
import asyncio

import pytest

from backend.ingestion.fetchers.pdf import fetch_pdf
from tests.conftest import make_pdf_bytes


@pytest.fixture
def short_pdf(tmp_path):
    p = tmp_path / "secret.pdf"
    p.write_bytes(make_pdf_bytes([
        "Personal Security Note",
        "My security code is Swordfish-Alpha-7723.",
        "Keep this code private.",
    ]))
    return str(p)


async def test_extracts_text_layer(short_pdf):
    docs = await fetch_pdf(short_pdf)
    assert len(docs) == 1
    doc = docs[0]
    assert "Swordfish-Alpha-7723" in doc["text"]
    assert doc["title"] == "secret"


async def test_doc_id_and_url_are_deterministic(short_pdf):
    first = (await fetch_pdf(short_pdf))[0]
    second = (await fetch_pdf(short_pdf))[0]
    # Same file -> same id and url, so chunk ids + the chunk-presence skip match.
    assert first["id"] == second["id"]
    assert first["url"] == short_pdf == second["url"]


async def test_empty_pdf_raises(tmp_path):
    # A PDF whose text layer is empty AND that OCR can't read should be a hard
    # error, not a silent "ready but empty" source.
    p = tmp_path / "blank.pdf"
    p.write_bytes(make_pdf_bytes([]))  # no text operators

    async def fake_ocr(_bytes):
        return ""  # simulate OCR also finding nothing

    import backend.core.llm_client as llm
    orig = getattr(llm, "ocr_pdf", None)
    llm.ocr_pdf = fake_ocr
    try:
        with pytest.raises(ValueError):
            await fetch_pdf(str(p))
    finally:
        if orig is not None:
            llm.ocr_pdf = orig
