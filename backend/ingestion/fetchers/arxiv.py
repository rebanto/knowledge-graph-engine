import re
import ssl
import asyncio
import feedparser
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

import aiohttp
import certifi

ARXIV_API = "https://export.arxiv.org/api/query"

# Verify TLS against certifi's CA bundle rather than the OS store, which is
# missing/stale on many Windows Python installs (SSL: CERTIFICATE_VERIFY_FAILED).
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

DEFAULT_CATEGORIES = ["cs.AI", "cs.LG", "cs.CL"]

_feed_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="feedparser")

# ── ID patterns ───────────────────────────────────────────────────────────────

# New-style: 2401.12345 or 2401.12345v2
_NEW_ID_RE = re.compile(r"\d{4}\.\d{4,5}(?:v\d+)?")
# Old-style: math/0211159v1, cs.AI/0001001
_OLD_ID_RE = re.compile(r"[a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?")
# ArXiv abs/pdf URL → capture the ID portion
_URL_RE = re.compile(
    r"https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/([^\s?#]+?)(?:\.pdf)?$",
    re.IGNORECASE,
)
# Category token: e.g. cs.AI, stat.ML, q-bio.NC
_CAT_TOKEN_RE = re.compile(r"^[a-z][a-z0-9-]*\.[A-Za-z][A-Za-z0-9-]*$")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_ids(query: str) -> list[str]:
    """Pull all arxiv IDs out of a raw query string (IDs and arxiv.org URLs)."""
    ids: list[str] = []
    for token in re.split(r"[,\s]+", query.strip()):
        if not token:
            continue
        url_m = _URL_RE.match(token)
        if url_m:
            ids.append(url_m.group(1))
            continue
        if _NEW_ID_RE.fullmatch(token) or _OLD_ID_RE.fullmatch(token):
            ids.append(token)
    return ids


def _looks_like_categories(query: str) -> bool:
    """True when every comma-separated token matches the category pattern."""
    tokens = [t.strip() for t in query.split(",") if t.strip()]
    return bool(tokens) and all(_CAT_TOKEN_RE.match(t) for t in tokens)


def _build_params(query: str, max_results: int, days_back: int) -> tuple[dict, str]:
    """
    Return (params_dict, mode) where mode is "id", "category", or "keyword".

    id       → explicit paper IDs / arxiv.org URLs; exact fetch, no date filter.
    category → category codes (cs.AI, stat.ML …); submittedDate filter applied.
    keyword  → everything else; relevance-sorted, no date filter.
    """
    ids = _extract_ids(query)
    if ids:
        return {"id_list": ",".join(ids), "max_results": len(ids)}, "id"

    if _looks_like_categories(query):
        tokens = [t.strip() for t in query.split(",") if t.strip()]
        cat_q = " OR ".join(f"cat:{c}" for c in tokens)
        start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")
        return {
            "search_query": f"({cat_q}) AND submittedDate:[{start_date}0000 TO 99991231235959]",
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }, "category"

    if query.strip():
        return {
            "search_query": f"all:{query.strip()}",
            "start": 0,
            "max_results": max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }, "keyword"

    # Empty / garbage → fall back to default categories
    cat_q = " OR ".join(f"cat:{c}" for c in DEFAULT_CATEGORIES)
    start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")
    return {
        "search_query": f"({cat_q}) AND submittedDate:[{start_date}0000 TO 99991231235959]",
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }, "category"


# ── Public fetcher ────────────────────────────────────────────────────────────

async def fetch_arxiv(query: str, max_results: int = 50, days_back: int = 90) -> list[dict]:
    params, mode = _build_params(query, max_results, days_back)

    connector = aiohttp.TCPConnector(ssl=_SSL_CONTEXT)
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=60), connector=connector
    ) as session:
        async with session.get(ARXIV_API, params=params) as resp:
            resp.raise_for_status()
            text = await resp.text()

    loop = asyncio.get_event_loop()
    feed = await loop.run_in_executor(_feed_executor, feedparser.parse, text)

    # For explicit ID lookups, an empty result means the IDs weren't found —
    # surface that as an error so the source card shows a failure rather than
    # "0 documents / success", which is a silent black hole.
    if mode == "id" and not feed.entries:
        ids = params.get("id_list", query)
        raise ValueError(
            f"ArXiv returned no results for the requested paper ID(s): {ids!r}. "
            "Check that the IDs exist and are publicly available."
        )

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
