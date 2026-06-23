import asyncio
from backend.db import neo4j as neo4j_db
from backend.db import chroma as chroma_db
from backend.ingestion.chunker import chunk_text
from backend.ingestion.entity_extractor import extract_entities
from backend.ingestion.entity_resolver import EntityResolver
from backend.ingestion.conflict_detector import check_and_flag_conflict


# How the Paper node is linked to each extracted entity type. This is the fix
# for the "graph is only authorship" problem: every concept/topic/method a paper
# discusses is now attached to that paper, so two papers covering the same concept
# become connected (Paper A)-[:MENTIONS]->(Concept X)<-[:MENTIONS]-(Paper B).
_PAPER_LINK = {
    "Concept": "MENTIONS",
    "Topic": "ABOUT",
    "Organization": "AFFILIATED_WITH",   # institution behind the work
    "Event": "PRESENTED_AT",
}

# Entity types we never link the Paper to directly (people are linked via AUTHORED;
# nested Paper entities are handled as CITED if the extractor surfaces them).
_PAPER_LINK_SKIP = {"Person", "Paper"}

# Entity extraction reads more of the document than before so the graph reflects
# the whole source, not just the abstract's first lines. The windowed extractor
# caps the number of LLM calls internally (_MAX_WINDOWS).
_EXTRACT_CHAR_LIMIT = 40_000


async def process_document(
    doc: dict, workspace_id: str, resolver: EntityResolver,
    force: bool = False, source_id: str = None,
) -> bool:
    """
    Returns True if the document was processed, False if already done (skipped).

    When force=True the "already processed" checkpoint is ignored, so the
    document is re-extracted and re-embedded. This is safe to replay because
    Neo4j writes use MERGE and ChromaDB writes use upsert with deterministic IDs.

    source_id is the Postgres Source row id; it is recorded on every node/edge so
    deleting that source can later detach exactly its contribution from the graph.
    """
    doc_id = doc["id"]
    title = doc["title"]
    body = f"{title}. {doc['text']}" if doc.get("text") else title

    # Deterministic per-document key (per CLAUDE.md). Computed up-front because it
    # is also the idempotency skip key. Fall back to doc_id when a source has no
    # URL (e.g. local PDF).
    chunk_source = doc.get("url") or doc_id

    # The skip is PER-WORKSPACE, keyed on whether THIS workspace already holds the
    # document's chunks. The Neo4j processed-flag is global (Paper nodes are keyed
    # by arxiv_id across all workspaces), so using it as the skip gate caused a
    # document ingested in workspace A to be skipped in workspace B — leaving B
    # with a green "success" source but zero searchable data. Checking this
    # workspace's ChromaDB collection makes the skip correct across workspaces
    # while still no-op'ing a genuine re-ingest of the same source.
    if not force and await chroma_db.has_chunks_for_source(workspace_id, chunk_source):
        return False

    categories = [c for c in (doc.get("categories") or []) if c]

    # 1. Paper node
    await neo4j_db.merge_paper(doc_id, title, workspace_id, {
        "url": doc.get("url", ""),
        "published": doc.get("published", ""),
        "categories": ", ".join(categories),
    }, source_id=source_id)

    # 2. Author nodes + AUTHORED edges (structured metadata — no LLM)
    for author_name in doc.get("authors", []):
        canonical = resolver.resolve(author_name, "Person")
        await neo4j_db.merge_node("Person", canonical, workspace_id, source_id=source_id)
        await neo4j_db.merge_edge(
            canonical, "Person",
            doc_id, "Paper",
            "AUTHORED", workspace_id,
            {"source_document_id": doc_id, "confidence": 1.0},
            source_id=source_id,
        )

    # 3. Categories → Topic nodes + (Paper)-[:ABOUT]->(Topic). These are exact,
    #    LLM-free, and connect every paper sharing a category — the backbone of
    #    inter-paper structure.
    for cat in categories:
        await neo4j_db.merge_node("Topic", cat, workspace_id, source_id=source_id)
        await neo4j_db.merge_edge(
            doc_id, "Paper",
            cat, "Topic",
            "ABOUT", workspace_id,
            {"source_document_id": doc_id, "confidence": 1.0},
            source_id=source_id,
        )

    # 4. Embed body chunks → ChromaDB (run in parallel with entity extraction)
    # chunk_source (deterministic, per CLAUDE.md) was computed above for the skip.
    chunks = chunk_text(body)

    async def _embed():
        # Replace any prior chunks for this document so a re-ingest is a clean
        # overwrite (handles ID-format changes and shrinking content).
        await chroma_db.delete_chunks_for_source(workspace_id, chunk_source)
        await chroma_db.add_chunks(workspace_id, [
            {
                "id": f"{workspace_id}:{chunk_source}:{i}",
                "text": chunk,
                "metadata": {
                    "source_url": doc.get("url", ""),
                    "source_title": title,
                    "source_date": doc.get("published", ""),
                    "chunk_index": i,
                    "workspace_id": workspace_id,
                    # Recorded so deleting a source can purge its chunks too.
                    "source_id": source_id or "",
                },
            }
            for i, chunk in enumerate(chunks)
        ])

    async def _extract():
        return await extract_entities(body[:_EXTRACT_CHAR_LIMIT])

    # Run embedding and entity extraction in parallel
    _, extraction = await asyncio.gather(_embed(), _extract())

    entity_type_map = {e["name"]: e["type"] for e in extraction["entities"]}
    resolved_names: dict[str, str] = {}

    # 5. Extracted entities → nodes, and link the Paper to each one so the
    #    document is connected to its own content (not just its authors).
    for entity in extraction["entities"]:
        etype = entity["type"]
        canonical = resolver.resolve(entity["name"], etype)
        resolved_names[entity["name"]] = canonical
        await neo4j_db.merge_node(etype, canonical, workspace_id, source_id=source_id)

        if etype in _PAPER_LINK_SKIP:
            continue
        link = _PAPER_LINK.get(etype, "MENTIONS")
        await neo4j_db.merge_edge(
            doc_id, "Paper",
            canonical, etype,
            link, workspace_id,
            {"source_document_id": doc_id, "confidence": 0.9},
            source_id=source_id,
        )

    # 6. Extracted relationships between entities (the conceptual structure).
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
            source_id=source_id,
        )

        if rel["type"] in ("SUPPORTS", "CONTRADICTS"):
            await check_and_flag_conflict(src, tgt, rel["type"], doc_id, workspace_id)

    await neo4j_db.mark_paper_processed(doc_id)
    return True
