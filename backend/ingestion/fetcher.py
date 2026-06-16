import requests
import feedparser
from datetime import datetime, timedelta

ARXIV_API = "http://export.arxiv.org/api/query"
CATEGORIES = ["cs.AI", "cs.LG", "cs.CL"]


def fetch_arxiv_papers(max_results: int = 500, days_back: int = 90) -> list[dict]:
    category_query = " OR ".join(f"cat:{c}" for c in CATEGORIES)
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
    papers = []

    for entry in feed.entries:
        arxiv_id = entry.id.split("/abs/")[-1]
        papers.append({
            "id": arxiv_id,
            "title": entry.title.replace("\n", " ").strip(),
            "abstract": entry.summary.replace("\n", " ").strip(),
            "authors": [a.name for a in getattr(entry, "authors", [])],
            "categories": [t.term for t in getattr(entry, "tags", [])],
            "url": entry.id,
            "published": entry.get("published", ""),
        })

    return papers
