#!/usr/bin/env python3
"""
Seed the knowledge graph with ArXiv AI/ML papers.
Usage: python scripts/seed_arxiv.py [--max 500] [--days 90]
"""
import sys
import time
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from backend.db.neo4j import setup_constraints, close_driver, get_node_count, get_edge_count
from backend.db.chroma import get_chunk_count
from backend.ingestion.fetcher import fetch_arxiv_papers
from backend.ingestion.worker import process_paper
from backend.ingestion.entity_resolver import EntityResolver

WORKSPACE_ID = "arxiv_seed"

# Gemini free tier: 15 RPM → 1 call per 4s to stay safe
# Each paper = 1 LLM call (entity extraction)
RATE_LIMIT_DELAY = 4.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=500, help="Max papers to ingest")
    parser.add_argument("--days", type=int, default=90, help="How many days back to fetch")
    args = parser.parse_args()

    print("Setting up Neo4j schema constraints...")
    setup_constraints()

    print(f"\nFetching up to {args.max} papers from ArXiv (last {args.days} days)...")
    papers = fetch_arxiv_papers(max_results=args.max, days_back=args.days)
    print(f"Fetched {len(papers)} papers.\n")

    resolver = EntityResolver(threshold=0.85)
    success, failed = 0, 0

    for i, paper in enumerate(papers, 1):
        print(f"[{i}/{len(papers)}] {paper['title'][:72]}...")
        try:
            process_paper(paper, WORKSPACE_ID, resolver)
            success += 1
        except Exception as e:
            print(f"  SKIP: {e}")
            failed += 1

        if i < len(papers):
            time.sleep(RATE_LIMIT_DELAY)

    close_driver()

    print(f"\n{'='*60}")
    print(f"Ingestion complete: {success} succeeded, {failed} failed")
    print(f"Neo4j nodes : {get_node_count()}")
    print(f"Neo4j edges : {get_edge_count()}")
    print(f"Chroma chunks: {get_chunk_count(WORKSPACE_ID)}")
    print(f"\nExplore the graph: http://localhost:7474")
    print(f"  MATCH (n) RETURN count(n)")
    print(f"  MATCH (p:Paper)<-[:AUTHORED]-(a:Person) RETURN p.name, collect(a.name) LIMIT 5")


if __name__ == "__main__":
    main()
