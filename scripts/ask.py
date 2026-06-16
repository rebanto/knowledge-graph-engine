#!/usr/bin/env python3
"""
Ask a natural language question against the knowledge graph.
Usage: python scripts/ask.py "How is researcher X connected to Y?"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from backend.db.neo4j import close_driver
from backend.core.qa_pipeline import answer_question

WORKSPACE_ID = "arxiv_seed"


def main():
    if len(sys.argv) < 2:
        print('Usage: python scripts/ask.py "your question here"')
        sys.exit(1)

    question = " ".join(sys.argv[1:])
    print(f"Q: {question}\n")

    try:
        result = answer_question(question, WORKSPACE_ID)

        print(f"[router] type={result['type']}  reasoning={result['reasoning']}")
        if result["cached"]:
            print("[cache] served from Redis cache")
        if result["cypher"]:
            print(f"[graph] cypher: {result['cypher']}")
            print(f"[graph] {len(result['graph_records'])} records")
        if result["vector_chunks"]:
            print(f"[vector] {len(result['vector_chunks'])} chunks retrieved")

        print("\n" + "=" * 60)
        print(result["answer"])
        print("=" * 60)
    finally:
        close_driver()


if __name__ == "__main__":
    main()
