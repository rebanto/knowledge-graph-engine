from backend.db import neo4j as neo4j_db
from backend.db import chroma as chroma_db
from backend.ingestion.chunker import chunk_text
from backend.ingestion.entity_extractor import extract_entities
from backend.ingestion.entity_resolver import EntityResolver


def process_paper(paper: dict, workspace_id: str, resolver: EntityResolver) -> bool:
    """Returns True if the paper was processed, False if it was already done (skipped)."""
    paper_id = paper["id"]
    title = paper["title"]
    text = f"{title}. {paper['abstract']}"

    if neo4j_db.is_paper_processed(paper_id):
        return False

    # 1. Paper node
    neo4j_db.merge_paper(paper_id, title, workspace_id, {
        "url": paper["url"],
        "published": paper["published"],
        "categories": ", ".join(paper["categories"]),
    })

    # 2. Author nodes + AUTHORED edges (structured from ArXiv metadata — no LLM needed)
    for author_name in paper["authors"]:
        resolved = resolver.resolve(author_name, "Person")
        neo4j_db.merge_node("Person", resolved, workspace_id)
        neo4j_db.merge_edge(
            resolved, "Person",
            paper_id, "Paper",
            "AUTHORED", workspace_id,
            {"source_document_id": paper_id, "confidence": 1.0},
        )

    # 3. Embed abstract chunks → ChromaDB
    chunks = chunk_text(text)
    chroma_db.add_chunks(workspace_id, [
        {
            "id": f"{paper_id}_chunk_{i}",
            "text": chunk,
            "metadata": {
                "source_url": paper["url"],
                "source_title": title,
                "source_date": paper["published"],
                "chunk_index": i,
                "workspace_id": workspace_id,
            },
        }
        for i, chunk in enumerate(chunks)
    ])

    # 4. LLM entity + relationship extraction from abstract
    extraction = extract_entities(text)

    entity_type_map = {e["name"]: e["type"] for e in extraction["entities"]}
    resolved_names: dict[str, str] = {}

    for entity in extraction["entities"]:
        canonical = resolver.resolve(entity["name"], entity["type"])
        resolved_names[entity["name"]] = canonical
        neo4j_db.merge_node(entity["type"], canonical, workspace_id)

    for rel in extraction["relationships"]:
        src_raw = rel.get("source", "")
        tgt_raw = rel.get("target", "")
        if src_raw not in resolved_names or tgt_raw not in resolved_names:
            continue

        src = resolved_names[src_raw]
        tgt = resolved_names[tgt_raw]
        src_type = entity_type_map.get(src_raw, "Concept")
        tgt_type = entity_type_map.get(tgt_raw, "Concept")

        neo4j_db.merge_edge(
            src, src_type,
            tgt, tgt_type,
            rel["type"], workspace_id,
            {
                "source_document_id": paper_id,
                "confidence": rel.get("confidence", 0.8),
                "context": rel.get("context", "")[:500],
            },
        )

    neo4j_db.mark_paper_processed(paper_id)
    return True
