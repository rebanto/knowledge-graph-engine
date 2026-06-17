from backend.core.llm_client import generate_json

VALID_ENTITY_TYPES = {"Person", "Organization", "Paper", "Concept", "Event", "Topic"}
VALID_EDGE_TYPES = {
    "AUTHORED", "CITED", "FUNDED_BY", "COLLABORATED_WITH",
    "PUBLISHED_IN", "SUPPORTS", "CONTRADICTS", "CONFLICTS_WITH",
}

EXTRACTION_PROMPT = """Extract named entities and relationships from this research paper text.
Return ONLY a JSON object — no markdown, no explanation, no code fences.

Schema:
{{
  "entities": [
    {{"name": "string", "type": "Person|Organization|Paper|Concept|Event|Topic", "aliases": []}}
  ],
  "relationships": [
    {{"source": "entity name", "target": "entity name", "type": "AUTHORED|CITED|FUNDED_BY|COLLABORATED_WITH|PUBLISHED_IN|SUPPORTS|CONTRADICTS", "context": "one sentence", "confidence": 0.0}}
  ]
}}

Rules:
- Concepts: algorithms, methods, datasets, model architectures, evaluation metrics, frameworks
- Topics: broad research areas and subfields
- Only include relationships where both source and target are in the entities list
- Do not include authors — they are handled separately
- Confidence: 0.9+ for explicit statements, 0.7-0.9 for strongly implied, below 0.7 skip it

Text:
{text}"""


async def extract_entities(text: str) -> dict:
    prompt = EXTRACTION_PROMPT.format(text=text[:4000])
    data = await generate_json(prompt)

    entities = [
        e for e in data.get("entities", [])
        if isinstance(e, dict) and e.get("type") in VALID_ENTITY_TYPES
    ]
    relationships = [
        r for r in data.get("relationships", [])
        if isinstance(r, dict) and r.get("type") in VALID_EDGE_TYPES
    ]

    return {"entities": entities, "relationships": relationships}
