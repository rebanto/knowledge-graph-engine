import hashlib
from pathlib import Path
from pypdf import PdfReader


def fetch_pdf(file_path: str, source_url: str = "") -> list[dict]:
    reader = PdfReader(file_path)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
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
