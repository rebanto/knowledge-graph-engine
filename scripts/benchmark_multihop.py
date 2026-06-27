#!/usr/bin/env python3
"""
Multi-hop reasoning benchmark — graph traversal vs vector search.

This is the empirical proof that the architecture earns its complexity: it runs
relationship questions that require ≥2 graph hops down BOTH retrieval paths
(forced graph-only and forced vector-only) and contrasts what each returns.

The point being demonstrated: vector search returns semantically similar passages
but structurally cannot perform a traversal — "concepts used by papers that cite
the most-cited paper" is a join across edges, not a similarity lookup. The graph
path returns the actual relationship records; the vector path returns prose that
can only approximate (or miss) the chained relationship. Both answers are printed
so the difference is visible, not asserted.

Requires the full local stack + a seeded workspace.

    python scripts/benchmark_multihop.py --workspace arxiv_seed
"""
import sys
import asyncio
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from backend.core.qa_pipeline import answer_question
from backend.eval.datasets import MULTIHOP


def _preview(text: str, n: int = 220) -> str:
    text = " ".join((text or "").split())
    return text[:n] + ("…" if len(text) > n else "")


async def _one(question: str, workspace: str) -> dict:
    graph = await answer_question(question, workspace, force_route="graph")
    vector = await answer_question(question, workspace, force_route="vector")
    return {
        "question": question,
        "graph_records": len(graph.get("graph_records") or []),
        "graph_answer": graph.get("answer", ""),
        "graph_cypher": graph.get("cypher"),
        "vector_chunks": len(vector.get("vector_chunks") or []),
        "vector_answer": vector.get("answer", ""),
    }


async def main(workspace: str) -> int:
    print(f"Multi-hop benchmark — workspace '{workspace}'\n"
          f"Each question is run graph-only and vector-only (forced routes).\n")
    line = "=" * 72

    graph_structured = 0
    for i, q in enumerate(MULTIHOP, 1):
        r = await _one(q, workspace)
        print(line)
        print(f"Q{i}. {q}")
        print(line)
        print(f"  GRAPH  : {r['graph_records']} relationship record(s)")
        if r["graph_cypher"]:
            print(f"           cypher: {_preview(r['graph_cypher'], 160)}")
        print(f"           {_preview(r['graph_answer'])}")
        print(f"  VECTOR : {r['vector_chunks']} passage(s) (no traversal possible)")
        print(f"           {_preview(r['vector_answer'])}\n")
        if r["graph_records"] > 0:
            graph_structured += 1

    print(line)
    print(f"SUMMARY: the graph path returned structured relationship records for "
          f"{graph_structured}/{len(MULTIHOP)} multi-hop questions.")
    print("The vector path can only return passages — it cannot express the "
          "chained relationships these questions ask for.")
    print(line)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default="arxiv_seed")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(main(args.workspace)))
