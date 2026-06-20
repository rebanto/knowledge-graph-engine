import ssl
import hashlib

import aiohttp
import certifi
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (compatible; KnowledgeGraphEngine/1.0; +ingestion bot)"

# Verify TLS against certifi's CA bundle (see arxiv.py for rationale).
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


async def fetch_web_url(url: str) -> list[dict]:
    headers = {"User-Agent": USER_AGENT}
    connector = aiohttp.TCPConnector(ssl=_SSL_CONTEXT)
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=20), connector=connector
    ) as session:
        async with session.get(url, headers=headers) as resp:
            resp.raise_for_status()
            text = await resp.text()

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
