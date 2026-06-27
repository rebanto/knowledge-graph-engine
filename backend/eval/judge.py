"""
LLM-as-judge faithfulness scoring.

The system's central claim is "the LLM never generates unsourced facts." This
module measures it: an independent LLM call decomposes an answer into atomic
factual claims and decides, for each, whether the RETRIEVED data supports it.
The complement — claims the answer asserts that retrieval did not support — is
the hallucination/unsupported-claim rate, the number that turns the claim from
an assertion into a measurement.

Deliberately separate from synthesizer.py: the judge sees only (answer,
retrieved_context) and never the question's "intended" answer, so it scores
grounding, not correctness-by-opinion.
"""
import json

from backend.core.llm_client import generate_json

JUDGE_PROMPT = """You are a strict fact-checking judge evaluating whether an answer is grounded in
its retrieved source data. You are NOT judging whether the answer is correct in general —
ONLY whether each claim is supported by the provided retrieved data.

Retrieved data the answer was allowed to use:
{context}

Answer to evaluate:
{answer}

Steps:
1. Decompose the answer into atomic factual claims (entities, relationships, numbers,
   citations). Ignore hedging, questions, and generic framing sentences.
2. For each claim, decide if it is SUPPORTED by the retrieved data above.
   A claim is supported only if the retrieved data contains the entity/relationship/number.
   General world knowledge that is NOT in the retrieved data counts as UNSUPPORTED.

Return ONLY JSON:
{{"claims": [{{"claim": "string", "supported": true|false}}]}}"""


def _context_str(results: dict, limit: int = 24000) -> str:
    """Flatten the retrieval payload (graph records, entity stats, vector
    passages, conflicts, influence) into the judge's evidence block."""
    return json.dumps(results, indent=2, default=str)[:limit]


async def judge_faithfulness(answer: str, results: dict) -> list[dict]:
    """Return [{"claim", "supported"}] for an answer given its retrieved data.

    On a judge failure or empty answer, returns [] — the aggregator treats an
    answer with no extracted claims as vacuously faithful, so a judge outage never
    fabricates a hallucination signal.
    """
    if not answer or not answer.strip():
        return []
    data = await generate_json(
        JUDGE_PROMPT.format(context=_context_str(results), answer=answer)
    )
    claims = data.get("claims")
    if not isinstance(claims, list):
        return []
    out = []
    for c in claims:
        if isinstance(c, dict) and "supported" in c:
            out.append({"claim": str(c.get("claim", ""))[:300],
                        "supported": bool(c["supported"])})
    return out


def supported_flags(claims: list[dict]) -> list[bool]:
    """Extract the bool support flags for the metrics layer."""
    return [bool(c.get("supported")) for c in claims]
