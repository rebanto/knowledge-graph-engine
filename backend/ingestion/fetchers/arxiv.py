import asyncio
import feedparser
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

import aiohttp

ARXIV_API = "http://export.arxiv.org/api/query"
DEFAULT_CATEGORIES = ["cs.AI", "cs.LG", "cs.CL"]

_feed_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="feedparser")


async def fetch_arxiv(query: str, max_results: int = 50, days_back: int = 90) -> list[dict]:
    categories = [c.strip() for c in query.split(",") if c.strip()] or DEFAULT_CATEGORIES
    category_query = " OR ".join(f"cat:{c}" for c in categories)
    start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")

    params = {
        "search_query": f"({category_query}) AND submittedDate:[{start_date}0000 TO 99991231235959]",
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        async with session.get(ARXIV_API, params=params) as resp:
            resp.raise_for_status()
            text = await resp.text()

    loop = asyncio.get_event_loop()
    feed = await loop.run_in_executor(_feed_executor, feedparser.parse, text)

    documents = []
    for entry in feed.entries:
        arxiv_id = entry.id.split("/abs/")[-1]
        documents.append({
            "id": arxiv_id,
            "title": entry.title.replace("\n", " ").strip(),
            "text": entry.summary.replace("\n", " ").strip(),
            "authors": [a.name for a in getattr(entry, "authors", [])],
            "categories": [t.term for t in getattr(entry, "tags", [])],
            "url": entry.id,
            "published": entry.get("published", ""),
        })

    return documents
