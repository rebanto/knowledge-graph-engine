import asyncio

from backend.core.llm_client import generate_json

VALID_ENTITY_TYPES = {"Person", "Organization", "Paper", "Concept", "Event", "Topic"}
VALID_EDGE_TYPES = {
    # Citation / authorship / collaboration
    "AUTHORED", "CITED", "COLLABORATED_WITH",
    # Affiliation & funding
    "AFFILIATED_WITH", "FUNDED_BY",
    # Conceptual relationships (the bulk of a paper's substance)
    "USES", "PROPOSES", "EXTENDS", "EVALUATED_ON", "APPLIED_TO",
    "PART_OF", "RELATED_TO", "IMPROVES", "COMPARED_TO",
    # Topic membership
    "PUBLISHED_IN",
    # Claim agreement / disagreement
    "SUPPORTS", "CONTRADICTS", "CONFLICTS_WITH",
}

# Each extraction window is sent to the LLM in one call. Windows overlap so an
# entity/relationship straddling a boundary is still captured in one of them.
_WINDOW_CHARS = 6000
_WINDOW_OVERLAP = 600
# Hard ceiling on LLM calls per document so a pathologically huge file can't
# fan out into hundreds of calls. ~15 windows ≈ 90k chars of coverage.
_MAX_WINDOWS = 15
# Bound concurrent LLM calls per document (the shared LLM pool has 8 workers).
_WINDOW_CONCURRENCY = 4

EXTRACTION_PROMPT = """You are building a knowledge graph from a research document. Extract the
named entities AND — most importantly — the relationships that connect them.
Return ONLY a JSON object — no markdown, no explanation, no code fences.

Schema:
{{
  "entities": [
    {{"name": "string", "type": "Person|Organization|Paper|Concept|Event|Topic", "aliases": []}}
  ],
  "relationships": [
    {{"source": "entity name", "target": "entity name", "type": "RELATION", "context": "one sentence", "confidence": 0.0}}
  ]
}}

Entity types:
- Concept: the technical substance — algorithms, methods, model architectures,
  datasets, benchmarks, evaluation metrics, techniques, tasks, frameworks, theorems.
  Extract these aggressively; they are what connect documents to each other.
- Topic: broad research areas / subfields (e.g. "reinforcement learning",
  "natural language processing", "computer vision").
- Organization: institutions, labs, companies, funding agencies.
- Person: only people explicitly named in the body as researchers/contributors
  (NOT the document's own authors — those are handled separately).
- Event: named conferences, workshops, or challenges.

Relationship types (source → target):
- PROPOSES    (Concept→Concept): a method introduces/defines another concept
- USES        (Concept→Concept): a method uses a technique, dataset, or component
- EXTENDS     (Concept→Concept): builds on / generalizes a prior method
- IMPROVES    (Concept→Concept): outperforms or refines another method
- COMPARED_TO (Concept→Concept): evaluated against a baseline/alternative
- EVALUATED_ON(Concept→Concept): a method is measured on a dataset/benchmark
- APPLIED_TO  (Concept→Topic|Concept): a method is applied to a task/domain
- PART_OF     (Concept→Concept): a component belongs to a larger system
- RELATED_TO  (Concept→Concept): related but no stronger relation fits
- AFFILIATED_WITH (Person→Organization): a person belongs to an institution
- FUNDED_BY   (Organization→Organization): funding relationship
- SUPPORTS / CONTRADICTS (Concept→Concept): a claim agrees with / disputes another
- PUBLISHED_IN (Concept→Topic): a concept sits within a research area

Rules:
- Prioritize RELATIONSHIPS. A document with 8 entities should usually yield 6+
  relationships. Connect the concepts to each other and to their topics.
- Only emit a relationship where BOTH source and target appear in "entities".
- Use the most specific relation type that fits; fall back to RELATED_TO only when
  nothing more specific applies.
- Confidence: 0.9+ explicit, 0.7-0.9 strongly implied, below 0.7 omit it.

Text:
{text}"""


def _windows(text: str) -> list[str]:
    """Split full text into overlapping char windows covering the entire document."""
    if len(text) <= _WINDOW_CHARS:
        return [text]

    windows: list[str] = []
    start = 0
    step = _WINDOW_CHARS - _WINDOW_OVERLAP
    while start < len(text) and len(windows) < _MAX_WINDOWS:
        windows.append(text[start:start + _WINDOW_CHARS])
        start += step
    return windows


async def _extract_window(text: str, sem: asyncio.Semaphore) -> dict:
    async with sem:
        return await generate_json(EXTRACTION_PROMPT.format(text=text))


async def extract_entities(text: str) -> dict:
    """Extract entities/relationships across the WHOLE document.

    The document is split into overlapping windows so the graph captures content
    from the entire source, not just the opening section. Per-window results are
    merged and de-duplicated (entities by name+type, relationships by
    source+target+type).
    """
    windows = _windows(text)
    sem = asyncio.Semaphore(_WINDOW_CONCURRENCY)

    window_results = await asyncio.gather(
        *[_extract_window(w, sem) for w in windows],
        return_exceptions=True,
    )

    entities_by_key: dict[tuple, dict] = {}
    rels_by_key: dict[tuple, dict] = {}

    for data in window_results:
        if isinstance(data, Exception) or not isinstance(data, dict):
            continue

        for e in data.get("entities", []):
            if not (isinstance(e, dict) and e.get("type") in VALID_ENTITY_TYPES):
                continue
            name = str(e.get("name", "")).strip()
            if not name:
                continue
            key = (name.lower(), e["type"])
            # First occurrence wins; merge aliases from later windows.
            if key not in entities_by_key:
                entities_by_key[key] = {"name": name, "type": e["type"], "aliases": list(e.get("aliases") or [])}
            else:
                existing = entities_by_key[key]
                for alias in e.get("aliases") or []:
                    if alias not in existing["aliases"]:
                        existing["aliases"].append(alias)

        for r in data.get("relationships", []):
            if not (isinstance(r, dict) and r.get("type") in VALID_EDGE_TYPES):
                continue
            src = str(r.get("source", "")).strip()
            tgt = str(r.get("target", "")).strip()
            if not src or not tgt:
                continue
            key = (src.lower(), tgt.lower(), r["type"])
            # Keep the highest-confidence instance of a repeated relationship.
            if key not in rels_by_key or r.get("confidence", 0) > rels_by_key[key].get("confidence", 0):
                rels_by_key[key] = r

    return {
        "entities": list(entities_by_key.values()),
        "relationships": list(rels_by_key.values()),
    }
