"""Unit tests for the pure evaluation metrics."""
from backend.eval.metrics import (
    confusion_matrix,
    routing_accuracy,
    retrieval_hit_rate,
    faithfulness_score,
    aggregate_faithfulness,
    precision_recall_f1,
)


def test_confusion_matrix_counts_and_zero_fills():
    pairs = [("graph", "graph"), ("graph", "vector"), ("vector", "vector"),
             ("hybrid", "graph")]
    cm = confusion_matrix(pairs)
    assert cm["graph"]["graph"] == 1
    assert cm["graph"]["vector"] == 1
    assert cm["vector"]["vector"] == 1
    assert cm["hybrid"]["graph"] == 1
    # every cell present, unused ones zero
    assert cm["vector"]["graph"] == 0


def test_confusion_matrix_buckets_unknown_prediction():
    cm = confusion_matrix([("graph", "weird")])
    assert cm["graph"]["other"] == 1


def test_routing_accuracy():
    assert routing_accuracy([("graph", "graph"), ("vector", "graph")]) == 0.5
    assert routing_accuracy([]) == 0.0


def test_retrieval_hit_rate():
    assert retrieval_hit_rate([True, True, False, True]) == 0.75
    assert retrieval_hit_rate([]) == 0.0


def test_faithfulness_score_and_vacuous():
    assert faithfulness_score([True, True, False, True]) == 0.75
    assert faithfulness_score([]) == 1.0  # no claims → vacuously faithful


def test_aggregate_faithfulness():
    per_answer = [[True, True], [True, False], []]
    agg = aggregate_faithfulness(per_answer)
    # per-answer scores: 1.0, 0.5, 1.0 → mean 0.8333
    assert abs(agg["mean_faithfulness"] - (2.5 / 3)) < 1e-9
    assert agg["total_claims"] == 4
    assert agg["unsupported_claims"] == 1
    assert abs(agg["unsupported_claim_rate"] - 0.25) < 1e-9
    assert agg["answers_with_unsupported"] == 1
    assert agg["num_answers"] == 3


def test_precision_recall_f1():
    # decisions: (predicted_merge, actual_same)
    decisions = [
        (True, True),    # tp
        (True, False),   # fp
        (False, True),   # fn
        (False, False),  # tn
        (True, True),    # tp
    ]
    m = precision_recall_f1(decisions)
    assert m["tp"] == 2 and m["fp"] == 1 and m["fn"] == 1 and m["tn"] == 1
    assert abs(m["precision"] - 2 / 3) < 1e-9
    assert abs(m["recall"] - 2 / 3) < 1e-9
    assert abs(m["f1"] - 2 / 3) < 1e-9
    assert abs(m["accuracy"] - 3 / 5) < 1e-9


def test_precision_recall_f1_empty():
    m = precision_recall_f1([])
    assert m["precision"] == 0.0 and m["f1"] == 0.0
