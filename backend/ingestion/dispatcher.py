from backend.ingestion.fetchers import arxiv, rss, web, pdf

FETCHERS = {
    "arxiv_feed": lambda source: arxiv.fetch_arxiv(source.url),
    "rss": lambda source: rss.fetch_rss(source.url),
    "web_url": lambda source: web.fetch_web_url(source.url),
    "pdf_upload": lambda source: pdf.fetch_pdf(source.url),
}


def fetch_documents_for_source(source) -> list[dict]:
    fetcher = FETCHERS.get(source.type)
    if fetcher is None:
        raise ValueError(f"Unknown source type: {source.type}")
    return fetcher(source)
