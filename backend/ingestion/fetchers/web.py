import hashlib
import requests
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (compatible; KnowledgeGraphEngine/1.0; +ingestion bot)"


def fetch_web_url(url: str) -> list[dict]:
    response = requests.get(url, timeout=20, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else url

    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    text = " ".join(soup.get_text(separator=" ").split())
    doc_id = hashlib.sha256(url.encode()).hexdigest()[:16]

    return [{
        "id": doc_id,
        "title": title,
        "text": text[:8000],
        "authors": [],
        "categories": [],
        "url": url,
        "published": "",
    }]
