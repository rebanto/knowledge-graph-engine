import asyncio
import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from pypdf import PdfReader

_pdf_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pdf")


def _read_pdf(file_path: str) -> str:
    reader = PdfReader(file_path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


async def fetch_pdf(file_path: str, source_url: str = "") -> list[dict]:
    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(_pdf_executor, _read_pdf, file_path)

    title = Path(file_path).stem
    doc_id = hashlib.sha256(file_path.encode()).hexdigest()[:16]

    return [{
        "id": doc_id,
        "title": title,
        "text": text[:20000],
        "authors": [],
        "categories": [],
        "url": source_url or file_path,
        "published": "",
    }]
