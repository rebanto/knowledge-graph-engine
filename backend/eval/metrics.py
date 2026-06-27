"""
Pure evaluation metrics for the quality benchmark.

No I/O here — every function takes already-collected results and returns numbers,
so the metric maths is unit-tested without a database or LLM. The orchestration
(running questions through the live pipeline, calling the judge) lives in
scripts/benchmark_quality.py.

Metrics implemented:
  * Routing — confusion matrix + accuracy over graph/vector/hybrid.
  * Retrieval — hit-rate (did retrieval surface the expected entity at all?).
  * Faithfulness — fraction of answer claims grounded in retrieved data, and the
    complementary unsupported-claim rate (the number that backs "not an LLM
    wrapper": claims the model asserted that the retrieval did NOT support).
  * Entity resolution — precision / recall / F1 of merge decisions vs labels.
"""
from collections import OrderedDict


# ── Routing ────────────────────────────────────────────────────────────────────

def confusion_matrix(pairs, labels=("graph", "vector", "hybrid")) -> "OrderedDict":
    """pairs: list of (expected_label, predicted_label).
    Returns expected → {predicted → count} with every label present (zero-filled).
    Unknown labels are bucketed under 'other'."""
    labels = list(labels)
    cols = labels + ["other"]
    cm = OrderedDict((e, OrderedDict((p, 0) for p in cols)) for e in labels)
    for expected, predicted in pairs:
        if expected not in cm:
            continue
        col = predicted if predicted in labels else "other"
        cm[expected][col] += 1
    return cm


def routing_accuracy(pairs) -> float:
    """Fraction of (expected, predicted) pairs that match."""
    if not pairs:
        return 0.0
    correct = sum(1 for e, p in pairs if e == p)
    return correct / len(pairs)


def format_confusion_matrix(cm) -> str:
    """Render the confusion matrix as an aligned text table (rows=expected)."""
    if not cm:
        return "(no routing data)"
    cols = list(next(iter(cm.values())).keys())
    header = f"{'exp / pred':<16}" + "".join(f"{c:>9}" for c in cols)
    lines = [header, "-" * len(header)]
    for expected, row in cm.items():
        lines.append(f"{expected:<16}" + "".join(f"{row[c]:>9}" for c in cols))
    return "\n".join(lines)


# ── Retrieval ──────────────────────────────────────────────────────────────────

def retrieval_hit_rate(hits) -> float:
    """hits: list of bool (did retrieval surface an expected entity for this Q?)."""
    if not hits:
        return 0.0
    return sum(1 for h in hits if h) / len(hits)


# ── Faithfulness ───────────────────────────────────────────────────────────────

def faithfulness_score(claim_flags) -> float:
    """Fraction of a single answer's claims that are supported by retrieved data.
    An answer with no extracted claims is treated as vacuously faithful (1.0)."""
    if not claim_flags:
        return 1.0
    return sum(1 for s in claim_flags if s) / len(claim_flags)


def aggregate_faithfulness(per_answer_claims) -> dict:
    """per_answer_claims: list of lists-of-bool (one inner list per answer).

    Returns:
      mean_faithfulness        — mean per-answer supported fraction
      unsupported_claim_rate   — fraction of ALL claims that were unsupported
      total_claims, unsupported_claims
      answers_with_unsupported — count of answers containing ≥1 unsupported claim
    """
    total = sum(len(c) for c in per_answer_claims)
    unsupported = sum(1 for c in per_answer_claims for s in c if not s)
    per_answer = [faithfulness_score(c) for c in per_answer_claims]
    mean_faith = sum(per_answer) / len(per_answer) if per_answer else 0.0
    answers_with_unsupported = sum(1 for c in per_answer_claims if any(not s for s in c))
    return {
        "mean_faithfulness": mean_faith,
        "unsupported_claim_rate": (unsupported / total) if total else 0.0,
        "total_claims": total,
        "unsupported_claims": unsupported,
        "answers_with_unsupported": answers_with_unsupported,
        "num_answers": len(per_answer_claims),
    }


# ── Entity resolution ──────────────────────────────────────────────────────────

def precision_recall_f1(decisions) -> dict:
    """decisions: list of (predicted_merge: bool, actual_same: bool).

    Treats a merge as the positive prediction and same-entity as the positive
    label, so precision = of the merges we made, how many were correct; recall =
    of the entities that should merge, how many we caught.
    """
    tp = sum(1 for p, a in decisions if p and a)
    fp = sum(1 for p, a in decisions if p and not a)
    fn = sum(1 for p, a in decisions if not p and a)
    tn = sum(1 for p, a in decisions if not p and not a)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    accuracy = (tp + tn) / len(decisions) if decisions else 0.0
    return {
        "precision": precision, "recall": recall, "f1": f1, "accuracy": accuracy,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
    }
