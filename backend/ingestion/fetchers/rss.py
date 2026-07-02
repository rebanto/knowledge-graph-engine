import asyncio
import ssl
from concurrent.futures import ThreadPoolExecutor

import aiohttp
import certifi
import feedparser

from backend.core.security import validate_public_http_url

# Verify TLS against certifi's CA bundle (see arxiv.py for rationale).
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

_feed_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="feedparser_rss")

# Feeds larger than this are truncated — a legitimate RSS document is far
# smaller, and this bounds memory against a hostile/misconfigured endpoint.
_MAX_FEED_BYTES = 10 * 1024 * 1024


async def fetch_rss(feed_url: str, max_items: int = 50) -> list[dict]:
    # SSRF guard + explicit timeout. Previously the URL went straight into
    # feedparser.parse, which fetches with blocking urllib and NO timeout — a
    # hung feed server would pin the executor thread forever.
    await asyncio.to_thread(validate_public_http_url, feed_url)

    connector = aiohttp.TCPConnector(ssl=_SSL_CONTEXT)
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=30), connector=connector
    ) as session:
        async with session.get(feed_url) as resp:
            resp.raise_for_status()
            raw = await resp.content.read(_MAX_FEED_BYTES)

    loop = asyncio.get_event_loop()
    parsed = await loop.run_in_executor(_feed_executor, feedparser.parse, raw)

    documents = []
    for entry in parsed.entries[:max_items]:
        text = entry.get("summary", "") or entry.get("description", "") or ""
        authors = [a.get("name", "") for a in entry.get("authors", [])] if entry.get("authors") else []
        documents.append({
            "id": entry.get("id") or entry.get("link", ""),
            "title": entry.get("title", "Untitled").strip(),
            "text": text.strip(),
            "authors": [a for a in authors if a],
            "categories": [t.term for t in entry.get("tags", [])] if entry.get("tags") else [],
            "url": entry.get("link", ""),
            "published": entry.get("published", ""),
        })

    return documents
