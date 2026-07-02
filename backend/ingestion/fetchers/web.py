import asyncio
import ssl
import hashlib

import aiohttp
import certifi
from bs4 import BeautifulSoup

from backend.core.security import validate_public_http_url

USER_AGENT = "Mozilla/5.0 (compatible; KnowledgeGraphEngine/1.0; +ingestion bot)"

# Verify TLS against certifi's CA bundle (see arxiv.py for rationale).
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

# Cap how much of a page we pull into memory. Pages past this are cut off, not
# failed — the head of an article carries the substance we chunk anyway.
_MAX_RESPONSE_BYTES = 10 * 1024 * 1024


async def _fetch_capped(url: str, timeout_secs: int = 20) -> str:
    """GET `url` and return its decoded body, reading at most _MAX_RESPONSE_BYTES."""
    headers = {"User-Agent": USER_AGENT}
    connector = aiohttp.TCPConnector(ssl=_SSL_CONTEXT)
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout_secs), connector=connector
    ) as session:
        async with session.get(url, headers=headers) as resp:
            resp.raise_for_status()
            raw = await resp.content.read(_MAX_RESPONSE_BYTES)
            return raw.decode(resp.charset or "utf-8", errors="replace")


async def fetch_web_url(url: str) -> list[dict]:
    # Re-validate at fetch time (defense in depth: the URL was checked when the
    # source was created, but DNS may have changed since — and older sources
    # predate the check entirely).
    await asyncio.to_thread(validate_public_http_url, url)

    text = await _fetch_capped(url)

    soup = BeautifulSoup(text, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else url

    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    body = " ".join(soup.get_text(separator=" ").split())
    doc_id = hashlib.sha256(url.encode()).hexdigest()[:16]

    return [{
        "id": doc_id,
        "title": title,
        "text": body,  # full page text — chunked downstream, no truncation
        "authors": [],
        "categories": [],
        "url": url,
        "published": "",
    }]
