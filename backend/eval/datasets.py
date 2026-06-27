"""
Labeled datasets for the quality benchmark.

These are intentionally checked into the repo (not generated) so the evaluation
is reproducible and reviewable. They target the default ArXiv AI/ML seed domain.

  GOLDEN           — questions with an expected route + entities that retrieval
                     should surface (the retrieval-hit proxy).
  RESOLUTION_PAIRS — entity-name pairs labeled same/different, for measuring the
                     resolver's precision/recall.
  MULTIHOP         — relationship questions that require ≥2 graph hops; used by
                     benchmark_multihop.py to contrast graph traversal vs vector
                     search (see docs/18-evaluation.md).
"""

# ── Routing + retrieval golden set ─────────────────────────────────────────────
# expected_route follows the router contract (graph = relationships between named
# entities; vector = knowledge/content; hybrid = both). expected_entities is the
# retrieval-hit proxy: retrieval "hit" if ANY of these strings appears (case-
# insensitively) in the graph records or vector passages the pipeline retrieved.
GOLDEN = [
    {
        "id": "g1",
        "question": "Who are the most prolific authors in this dataset?",
        "expected_route": "graph",
        "expected_entities": ["author"],
    },
    {
        "id": "g2",
        "question": "How is the Transformer architecture connected to attention mechanisms?",
        "expected_route": "graph",
        "expected_entities": ["Transformer", "attention"],
    },
    {
        "id": "g3",
        "question": "Which methods are most often compared against BERT?",
        "expected_route": "graph",
        "expected_entities": ["BERT"],
    },
    {
        "id": "g4",
        "question": "Which concepts are most central in this knowledge graph?",
        "expected_route": "graph",
        "expected_entities": [],
    },
    {
        "id": "g5",
        "question": "Which datasets are most frequently used for evaluation?",
        "expected_route": "graph",
        "expected_entities": ["dataset"],
    },
    {
        "id": "v1",
        "question": "What are the latest findings on reinforcement learning from human feedback?",
        "expected_route": "vector",
        "expected_entities": ["reinforcement learning"],
    },
    {
        "id": "v2",
        "question": "Summarize the current state of research on diffusion models.",
        "expected_route": "vector",
        "expected_entities": ["diffusion"],
    },
    {
        "id": "v3",
        "question": "What are the open problems in large language model alignment?",
        "expected_route": "vector",
        "expected_entities": ["alignment", "language model"],
    },
    {
        "id": "v4",
        "question": "What evidence exists for scaling laws in neural networks?",
        "expected_route": "vector",
        "expected_entities": ["scaling"],
    },
    {
        "id": "v5",
        "question": "What are the main approaches to model compression?",
        "expected_route": "vector",
        "expected_entities": ["compression"],
    },
    {
        "id": "h1",
        "question": ("Which institutions are most active in transformer research, "
                     "and what do their papers focus on?"),
        "expected_route": "hybrid",
        "expected_entities": ["Transformer"],
    },
    {
        "id": "h2",
        "question": "Summarize the work connected to the most influential authors and their collaborators.",
        "expected_route": "hybrid",
        "expected_entities": ["author"],
    },
]


# ── Entity-resolution labeled pairs ────────────────────────────────────────────
# (name_a, name_b, entity_type, same_entity)
RESOLUTION_PAIRS = [
    ("BERT", "Bidirectional Encoder Representations from Transformers", "Concept", True),
    ("LSTM", "Long Short-Term Memory", "Concept", True),
    ("CNN", "Convolutional Neural Network", "Concept", True),
    ("GAN", "Generative Adversarial Network", "Concept", True),
    ("Adam", "Adam optimizer", "Concept", True),
    ("transformer", "Transformer", "Concept", True),
    ("Geoffrey Hinton", "G. Hinton", "Person", True),
    ("OpenAI", "Open AI", "Organization", True),
    ("DeepMind", "Google DeepMind", "Organization", True),
    ("GPT-4", "GPT-4o", "Concept", False),
    ("ResNet", "DenseNet", "Concept", False),
    ("BERT", "RoBERTa", "Concept", False),
    ("ImageNet", "CIFAR-10", "Concept", False),
    ("Yann LeCun", "Yoshua Bengio", "Person", False),
    ("MIT", "Stanford", "Organization", False),
    ("attention", "self-attention", "Concept", False),
]


# ── Multi-hop relationship questions (graph-vs-vector differentiation) ──────────
# These need a traversal vector search structurally cannot perform: chained
# relationships across multiple entities. The benchmark runs each through the
# graph path and the vector-only path and contrasts which produced a grounded,
# relationship-bearing answer.
MULTIHOP = [
    # "Friend of a friend" — a two-hop join through a shared collaborator. Vector
    # search has no notion of a shared neighbour; this is structurally a graph op.
    "Find researchers who share a co-author but have not written a paper together.",
    # Variable-length transitive path — degrees of separation between researchers.
    "Which researchers are connected to each other through a chain of collaborations?",
    # Two-hop join: papers linked via a shared author (Paper←AUTHORED→Person→AUTHORED→Paper).
    "Which papers are connected to other papers through a shared author?",
    # The conflict USP — a concept SUPPORTED by one source and CONTRADICTED by another.
    "Which concepts are contradicted by one source but supported by another?",
    # Claim chains — following SUPPORTS edges from one concept to another.
    "What chains of SUPPORTS relationships connect one concept to another?",
]
