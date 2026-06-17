import asyncio
from backend.db import neo4j as neo4j_db
from backend.db import chroma as chroma_db
from backend.ingestion.chunker import chunk_text
from backend.ingestion.entity_extractor import extract_entities
from backend.ingestion.entity_resolver import EntityResolver
from backend.ingestion.conflict_detector import check_and_flag_conflict


async def process_document(doc: dict, workspace_id: str, resolver: EntityResolver) -> bool:
    """
    Returns True if the document was processed, False if already done (skipped).
    """
    doc_id = doc["id"]
    title = doc["title"]
    body = f"{title}. {doc['text']}" if doc.get("text") else title

    if await neo4j_db.is_paper_processed(doc_id):
        return False

    # 1. Paper node
    await neo4j_db.merge_paper(doc_id, title, workspace_id, {
        "url": doc.get("url", ""),
        "published": doc.get("published", ""),
        "categories": ", ".join(doc.get("categories", [])),
    })

    # 2. Author nodes + AUTHORED edges (structured metadata — no LLM)
    for author_name in doc.get("authors", []):
        canonical = resolver.resolve(author_name, "Person")
        await neo4j_db.merge_node("Person", canonical, workspace_id)
        await neo4j_db.merge_edge(
            canonical, "Person",
            doc_id, "Paper",
            "AUTHORED", workspace_id,
            {"source_document_id": doc_id, "confidence": 1.0},
        )

    # 3. Embed body chunks → ChromaDB (run in parallel with entity extraction)
    chunks = chunk_text(body)

    async def _embed():
        await chroma_db.add_chunks(workspace_id, [
            {
                "id": f"{doc_id}_chunk_{i}",
                "text": chunk,
                "metadata": {
                    "source_url": doc.get("url", ""),
                    "source_title": title,
                    "source_date": doc.get("published", ""),
                    "chunk_index": i,
                    "workspace_id": workspace_id,
                },
            }
            for i, chunk in enumerate(chunks)
        ])

    async def _extract():
        return await extract_entities(body)

    # Run embedding and entity extraction in parallel
    _, extraction = await asyncio.gather(_embed(), _extract())

    entity_type_map = {e["name"]: e["type"] for e in extraction["entities"]}
    resolved_names: dict[str, str] = {}

    for entity in extraction["entities"]:
        canonical = resolver.resolve(entity["name"], entity["type"])
        resolved_names[entity["name"]] = canonical
        await neo4j_db.merge_node(entity["type"], canonical, workspace_id)

    for rel in extraction["relationships"]:
        src_raw = rel.get("source", "")
        tgt_raw = rel.get("target", "")
        if src_raw not in resolved_names or tgt_raw not in resolved_names:
            continue

        src = resolved_names[src_raw]
        tgt = resolved_names[tgt_raw]
        src_type = entity_type_map.get(src_raw, "Concept")
        tgt_type = entity_type_map.get(tgt_raw, "Concept")

        await neo4j_db.merge_edge(
            src, src_type,
            tgt, tgt_type,
            rel["type"], workspace_id,
            {
                "source_document_id": doc_id,
                "confidence": rel.get("confidence", 0.8),
                "context": rel.get("context", "")[:500],
            },
        )

        if rel["type"] in ("SUPPORTS", "CONTRADICTS"):
            await check_and_flag_conflict(src, tgt, rel["type"], doc_id, workspace_id)

    await neo4j_db.mark_paper_processed(doc_id)
    return True
