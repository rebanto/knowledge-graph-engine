import asyncio
import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from pypdf import PdfReader

_pdf_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pdf")


def _read_pdf(file_path: str) -> str:
    reader = PdfReader(file_path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


# Below this many extracted characters we suspect the PDF is scanned/image-only
# (the text layer is empty or near-empty) and fall back to Gemini OCR. This is a
# "should we try OCR" trigger, NOT a minimum acceptable length — a genuinely
# short PDF (e.g. a one-line note) is perfectly valid and is kept as-is.
_OCR_TRIGGER_CHARS = 20


async def fetch_pdf(file_path: str, source_url: str = "") -> list[dict]:
    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(_pdf_executor, _read_pdf, file_path)
    text = (text or "").strip()

    title = Path(file_path).stem

    # If the embedded text layer is empty/near-empty the PDF is likely scanned or
    # image-only. Try Gemini document OCR before giving up. We keep whichever
    # source yields more text, so a real (if short) text layer is never discarded.
    if len(text) < _OCR_TRIGGER_CHARS:
        try:
            from backend.core.llm_client import ocr_pdf
            pdf_bytes = await loop.run_in_executor(_pdf_executor, Path(file_path).read_bytes)
            ocr_text = (await ocr_pdf(pdf_bytes)).strip()
            if len(ocr_text) > len(text):
                text = ocr_text
        except Exception:
            # OCR unavailable/failed — fall through; we still raise below only if
            # there is genuinely no text at all from either path.
            pass

    # Only a TRULY empty result (no text layer AND OCR produced nothing) is a
    # failure. Any non-empty text — however short — is a valid, searchable doc.
    if not text:
        raise ValueError(
            f"PDF '{title}' produced no extractable text and OCR found none. "
            "It may be blank or an unsupported image format."
        )

    doc_id = hashlib.sha256(file_path.encode()).hexdigest()[:16]

    return [{
        "id": doc_id,
        "title": title,
        "text": text,  # full document — chunked downstream, no truncation
        "authors": [],
        "categories": [],
        "url": source_url or file_path,
        "published": "",
    }]
