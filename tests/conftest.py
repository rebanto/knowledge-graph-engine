"""Shared pytest fixtures + helpers for the knowledge-graph-engine test suite.

Layout:
  test_chunker.py          – pure unit, no services
  test_pdf_fetcher.py      – pure unit (builds a real PDF in-memory)
  test_vector_ingest.py    – in-process ChromaDB in a tmp dir (no server)
  test_routing_fallback.py – qa_pipeline routing, retrievers stubbed (no LLM/DB)
  test_graph_multitenancy.py – live Neo4j integration (auto-skips if unavailable)

The Neo4j tests use throwaway workspace ids and clean up after themselves, so
they never touch real workspace data.
"""
import os
import uuid

from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("AUTH_SECRET_KEY", "test-auth-secret-" + ("0" * 48))


def make_pdf_bytes(lines: list[str]) -> bytes:
    """Build a minimal, valid single-page PDF with a real text layer.

    No third-party PDF writer is available in the env, so we assemble the object
    table + xref by hand. pypdf can extract the embedded text from the result.
    """
    cl = ["BT", "/F1 14 Tf", "72 720 Td", "16 TL"]
    first = True
    for ln in lines:
        esc = ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        if not first:
            cl.append("T*")
        cl.append(f"({esc}) Tj")
        first = False
    cl.append("ET")
    content = "\n".join(cl).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += str(i).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    xref_pos = len(pdf)
    n = len(objects)
    pdf += b"xref\n0 " + str(n + 1).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        pdf += ("%010d 00000 n \n" % off).encode()
    pdf += (b"trailer\n<< /Size " + str(n + 1).encode() + b" /Root 1 0 R >>\n"
            b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF")
    return pdf


def unique_ws(prefix: str = "test_ws") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"
