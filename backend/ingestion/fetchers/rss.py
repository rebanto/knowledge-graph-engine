import feedparser


def fetch_rss(feed_url: str, max_items: int = 50) -> list[dict]:
    parsed = feedparser.parse(feed_url)
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
