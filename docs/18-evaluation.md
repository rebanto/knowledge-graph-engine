# Evaluation

The sharding work (Phase 4) is benchmarked with real latency numbers; this
document applies the same empirical discipline to the **AI quality** of the
system. The claims "the LLM never invents facts" and "graph traversal answers
questions vector search can't" are not asserted here — they are measured.

Two scripts produce the numbers, both in the same plain-table style as
[`benchmark_sharding.py`](14-scripts.md):

| Script | Question it answers |
|--------|---------------------|
| [`scripts/benchmark_quality.py`](../scripts/benchmark_quality.py) | How good are routing, retrieval, faithfulness, and entity resolution? |
| [`scripts/benchmark_multihop.py`](../scripts/benchmark_multihop.py) | Does graph traversal actually beat vector search on multi-hop questions? |

The labeled datasets they run against are checked into
[`backend/eval/datasets.py`](../backend/eval/datasets.py) so the evaluation is
reproducible and reviewable. The metric maths lives in
[`backend/eval/metrics.py`](../backend/eval/metrics.py) (pure functions, unit-tested
in `tests/test_eval_metrics.py`).

---

## 1. Quality benchmark

```
python scripts/benchmark_quality.py --workspace arxiv_seed
python scripts/benchmark_quality.py --workspace arxiv_seed --no-faithfulness  # skip LLM judge
```

It runs the golden question set through the **live pipeline** (`answer_question`)
and reports four things.

### Routing accuracy + confusion matrix

Each golden question carries an `expected_route` (`graph` / `vector` / `hybrid`).
The benchmark compares it against the router's actual classification and prints a
confusion matrix, so misroutings are visible by direction (e.g. graph questions
leaking to vector).

### Retrieval hit-rate

Did retrieval surface the entity the question is about? A question carries
`expected_entities`; a **hit** means at least one of them appears in the graph
records or vector passages the pipeline retrieved. (A deliberately coarse proxy —
it measures "did we retrieve the right neighbourhood", not ranking quality;
ranking quality is what the cross-encoder reranker improves.)

### Faithfulness — the "not an LLM wrapper" number

This is the headline metric. An independent LLM judge
([`backend/eval/judge.py`](../backend/eval/judge.py)) sees only the answer and the
retrieved data, decomposes the answer into atomic claims, and decides for each
whether the **retrieved data supports it**. World knowledge that isn't in the
retrieved data counts as *unsupported*.

- **mean faithfulness** — average fraction of an answer's claims that are grounded.
- **unsupported-claim rate** — fraction of all claims the model asserted that
  retrieval did **not** support. This is the hallucination number; the design
  goal (grounded synthesis, every fact traceable) is that it stays near zero.

The judge fails closed: a judge outage yields zero claims for that answer, which
the aggregator treats as vacuously faithful rather than inventing a false signal.

### Entity-resolution precision / recall / F1

The resolver's merge decisions are measured against labeled name pairs
(`RESOLUTION_PAIRS`) via `EntityResolver.decide_pair`. A *merge* is the positive
prediction; *same entity* is the positive label. Precision = of the merges we
made, how many were correct (low precision = collapsing distinct entities);
recall = of the entities that should merge, how many we caught (low recall =
duplicate nodes). See [Ingestion → entity resolution](06-ingestion-pipeline.md).

---

## 2. Multi-hop benchmark — the differentiation proof

```
python scripts/benchmark_multihop.py --workspace arxiv_seed
```

Each question in `MULTIHOP` requires **≥2 graph hops** — a join across edges, not
a similarity lookup ("concepts used by papers that cite the most-cited paper").
The script runs every question down both retrieval paths using the
`force_route` hook on `answer_question` (graph-only vs vector-only, no
cross-retriever fallback, so the comparison is clean) and prints both answers
side by side.

What it demonstrates: the graph path returns the actual relationship records and
the Cypher that produced them; the vector path returns semantically similar
passages but **structurally cannot perform the traversal**, so its answer can
only approximate or miss the chained relationship. This is the concrete reason
the graph half of the architecture is not redundant with the vector half.

---

## How this maps to what a reviewer asks

| Reviewer question | Where the number comes from |
|-------------------|------------------------------|
| "How do you know it doesn't hallucinate?" | Faithfulness / unsupported-claim rate (`benchmark_quality.py`) |
| "Is the router any good?" | Routing accuracy + confusion matrix |
| "Does the graph earn its complexity vs plain RAG?" | `benchmark_multihop.py` side-by-side |
| "Entity resolution is hard — does yours work?" | Resolution precision / recall / F1 |

> The numbers depend on the seeded data, so they are intentionally **not**
> hard-coded here — run the scripts against your workspace and read them off.
> The harness, datasets, and metric definitions are fixed; the measurement is
> reproducible.
