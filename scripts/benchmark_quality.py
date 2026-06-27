#!/usr/bin/env python3
"""
Answer-quality benchmark — the AI-side counterpart to benchmark_sharding.py.

Where the sharding benchmark measures latency, this measures whether the system
actually does what it claims. It runs the checked-in golden set through the live
pipeline and reports, in the same plain-table style:

  1. Routing accuracy + confusion matrix   (graph / vector / hybrid)
  2. Retrieval hit-rate                     (did retrieval surface the expected entity?)
  3. Faithfulness                           (fraction of answer claims grounded in
                                             retrieved data) and the UNSUPPORTED-claim
                                             rate — the number that backs "not an LLM
                                             wrapper": claims the model asserted that
                                             the retrieval did not support.
  4. Entity-resolution precision / recall / F1 against labeled pairs.

Requires the full local stack (Neo4j/Chroma/Redis) and a Gemini key, plus a
seeded workspace. Faithfulness + borderline resolution make LLM calls; pass
--no-faithfulness to skip the judge (e.g. when conserving free-tier quota).

    python scripts/benchmark_quality.py --workspace arxiv_seed
    python scripts/benchmark_quality.py --workspace arxiv_seed --no-faithfulness
"""
import sys
import logging
import asyncio
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Windows consoles default to cp1252, which can't encode the arrows/≥ used in the
# report; force UTF-8 so the output renders instead of crashing.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
# Under sharding the scatter-gather read hits every shard, and shards that don't
# hold a given label/relationship return a harmless WARNING notification. Quiet
# them so the benchmark output is clean.
logging.getLogger("neo4j").setLevel(logging.ERROR)

from dotenv import load_dotenv
load_dotenv()

from backend.core.qa_pipeline import answer_question
from backend.eval import metrics
from backend.eval.datasets import GOLDEN, RESOLUTION_PAIRS
from backend.eval.judge import judge_faithfulness, supported_flags
from backend.ingestion.entity_resolver import EntityResolver


def _haystack(result: dict) -> str:
    """Lowercased blob of everything retrieval surfaced, for the hit check."""
    parts = []
    for rec in result.get("graph_records", []) or []:
        parts.append(str(rec))
    for ch in result.get("vector_chunks", []) or []:
        parts.append(str(ch.get("text", "")))
        parts.append(str(ch.get("source_title", "")))
    return " ".join(parts).lower()


def _retrieval_hit(result: dict, expected_entities: list[str]) -> bool:
    hay = _haystack(result)
    if not expected_entities:
        # No specific target — count as a hit if retrieval returned anything at all.
        return bool(result.get("graph_records") or result.get("vector_chunks"))
    return any(e.lower() in hay for e in expected_entities)


async def _run_golden(workspace: str, do_faithfulness: bool, limit: int | None):
    items = GOLDEN[:limit] if limit else GOLDEN
    routing_pairs, hits, per_answer_claims = [], [], []

    print(f"Running {len(items)} golden questions against workspace '{workspace}'…\n")
    for item in items:
        result = await answer_question(item["question"], workspace)
        predicted = result.get("type", "?")
        routing_pairs.append((item["expected_route"], predicted))
        hit = _retrieval_hit(result, item.get("expected_entities", []))
        hits.append(hit)

        ok = "OK " if predicted == item["expected_route"] else "MISS"
        flag = "hit " if hit else "miss"
        print(f"  [{item['id']:<3}] route {ok} (exp {item['expected_route']:<6} → "
              f"got {predicted:<6}) retrieval {flag}  {item['question'][:60]}")

        if do_faithfulness:
            payload = {
                "graph_records": result.get("graph_records", []),
                "vector_passages": result.get("vector_chunks", []),
                "conflicts": result.get("conflicts", []),
            }
            claims = await judge_faithfulness(result.get("answer", ""), payload)
            per_answer_claims.append(supported_flags(claims))

    return routing_pairs, hits, per_answer_claims


async def _run_resolution():
    resolver = EntityResolver()
    decisions = []
    for a, b, etype, same in RESOLUTION_PAIRS:
        pred = await resolver.decide_pair(a, b, etype)
        decisions.append((pred, same))
    return decisions


def _print_report(routing_pairs, hits, per_answer_claims, decisions, did_faith):
    line = "=" * 60
    print("\n" + line)
    print("QUALITY BENCHMARK RESULTS")
    print(line)

    # 1. Routing
    acc = metrics.routing_accuracy(routing_pairs)
    print(f"\n[1] Routing accuracy: {acc:.1%}  ({len(routing_pairs)} questions)\n")
    print(metrics.format_confusion_matrix(metrics.confusion_matrix(routing_pairs)))

    # 2. Retrieval
    print(f"\n[2] Retrieval hit-rate: {metrics.retrieval_hit_rate(hits):.1%}  "
          f"({sum(hits)}/{len(hits)} questions surfaced an expected entity)")

    # 3. Faithfulness
    if did_faith:
        agg = metrics.aggregate_faithfulness(per_answer_claims)
        print(f"\n[3] Faithfulness (grounding in retrieved data):")
        print(f"      mean faithfulness      : {agg['mean_faithfulness']:.1%}")
        print(f"      UNSUPPORTED-claim rate : {agg['unsupported_claim_rate']:.1%}  "
              f"({agg['unsupported_claims']}/{agg['total_claims']} claims)")
        print(f"      answers w/ ≥1 unsupported: {agg['answers_with_unsupported']}"
              f"/{agg['num_answers']}")
    else:
        print("\n[3] Faithfulness: skipped (--no-faithfulness)")

    # 4. Entity resolution
    m = metrics.precision_recall_f1(decisions)
    print(f"\n[4] Entity resolution ({len(decisions)} labeled pairs):")
    print(f"      precision {m['precision']:.1%}  recall {m['recall']:.1%}  "
          f"F1 {m['f1']:.1%}  accuracy {m['accuracy']:.1%}")
    print(f"      tp={m['tp']} fp={m['fp']} fn={m['fn']} tn={m['tn']}")
    print("\n" + line)


async def main(workspace: str, do_faithfulness: bool, limit: int | None) -> int:
    routing_pairs, hits, per_answer_claims = await _run_golden(
        workspace, do_faithfulness, limit)
    decisions = await _run_resolution()
    _print_report(routing_pairs, hits, per_answer_claims, decisions, do_faithfulness)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default="arxiv_seed")
    ap.add_argument("--no-faithfulness", action="store_true",
                    help="skip the LLM faithfulness judge (saves quota)")
    ap.add_argument("--limit", type=int, default=None,
                    help="run only the first N golden questions")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(
        main(args.workspace, not args.no_faithfulness, args.limit)))
