import requests
import feedparser
from datetime import datetime, timedelta

ARXIV_API = "http://export.arxiv.org/api/query"
DEFAULT_CATEGORIES = ["cs.AI", "cs.LG", "cs.CL"]


def fetch_arxiv(query: str, max_results: int = 50, days_back: int = 90) -> list[dict]:
    """
    query: comma-separated ArXiv category codes, e.g. "cs.AI,cs.LG,cs.CL".
    Falls back to a sane default if blank.
    """
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

    response = requests.get(ARXIV_API, params=params, timeout=60)
    response.raise_for_status()

    feed = feedparser.parse(response.text)
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
