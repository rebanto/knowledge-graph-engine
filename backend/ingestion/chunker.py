def chunk_text(text: str, chunk_size: int = 400, overlap: int = 40) -> list[str]:
    """Split text into overlapping word-count chunks (~512 tokens each)."""
    words = text.split()
    if len(words) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start += chunk_size - overlap

    return chunks
