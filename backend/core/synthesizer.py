import json
from backend.core.llm_client import generate_text

SYNTHESIS_PROMPT = """Answer the research question using ONLY the structured results below.
Do not use any outside knowledge. Cite sources inline using the paper titles or entity names given.

The results were already retrieved by a query built specifically to answer this question —
e.g. "graph" records are rows from a database query that matched the entities named in the
question (their names may not be repeated in every row, but the rows ARE the answer to the
question). "vector" chunks are document excerpts semantically matched to the question.

Only say there is not enough information if the results list is genuinely empty or clearly
unrelated to the question.

Question: {question}

Retrieved results (JSON):
{results}

Write a concise, well-cited prose answer."""


def synthesize_answer(question: str, results: dict) -> str:
    return generate_text(
        SYNTHESIS_PROMPT.format(question=question, results=json.dumps(results, indent=2)[:6000])
    )
