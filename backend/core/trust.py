"""Shared trust-score helpers.

Deep Research already uses the LLM judge to score a fused report. Regular
answers should surface the same product promise, so this module keeps the score
shape consistent across both paths while letting callers fail gracefully when the
judge is unavailable.
"""


def trust_from_claims(claims: list[dict]) -> dict:
    total = len(claims)
    supported = sum(1 for c in claims if c.get("supported"))
    unsupported = [c.get("claim", "") for c in claims if not c.get("supported")]
    return {
        "score": round(supported / total, 3) if total else None,
        "supported": supported,
        "total": total,
        "unsupported_claims": unsupported[:10],
        "claims": [
            {
                "claim": str(c.get("claim", ""))[:300],
                "supported": bool(c.get("supported")),
            }
            for c in claims[:16]
        ],
    }


def unavailable_trust() -> dict:
    return {
        "score": None,
        "supported": 0,
        "total": 0,
        "unsupported_claims": [],
        "claims": [],
    }
