from backend.core.llm_client import generate_json

VALID_TYPES = {"graph", "vector", "hybrid"}

ROUTER_PROMPT = """Classify this research question about a knowledge graph of AI/ML papers.
Return ONLY JSON: {{"type": "graph"|"vector"|"hybrid", "reasoning": "one sentence"}}

- "graph": questions about relationships between entities — who authored what, who collaborated
  with whom, what connects to what, paths between entities, counts of relationships.
- "vector": questions asking for knowledge or content — summarize findings, what does research
  say about X, open problems, evidence for a claim.
- "hybrid": questions that need both — e.g. "summarize the work of researchers connected to X".

Question: {question}"""


def classify_question(question: str) -> dict:
    data = generate_json(ROUTER_PROMPT.format(question=question))
    qtype = data.get("type")
    if qtype not in VALID_TYPES:
        qtype = "hybrid"
    return {"type": qtype, "reasoning": data.get("reasoning", "")}
