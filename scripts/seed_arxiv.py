#!/usr/bin/env python3
"""
Seed the knowledge graph with ArXiv AI/ML papers.
Usage: python scripts/seed_arxiv.py [--max 500] [--days 90]

This script runs outside the web server. It populates Neo4j and ChromaDB
directly (no RQ worker required) and marks each source as "success" in
Postgres so the UI shows accurate status.

Rate limits (free Gemini tier):
  ~10 RPM → 1 call per 7 s to stay safe.
  Daily cap (RPD): if you hit a 429 "PerDay" error, resume tomorrow.
"""
import sys
import asyncio
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from backend.db.neo4j import (
    setup_constraints, close_driver,
    get_node_count, get_edge_count,
)
from backend.db.chroma import get_chunk_count
from backend.ingestion.fetchers.arxiv import fetch_arxiv
from backend.ingestion.worker import process_document
from backend.ingestion.entity_resolver import EntityResolver
from backend.core.llm_client import DailyQuotaExhausted

WORKSPACE_ID = "arxiv_seed"
RATE_LIMIT_DELAY = 7.0   # seconds between LLM calls (free-tier safety margin)


async def _seed(max_papers: int, days_back: int) -> None:
    print("Setting up Neo4j schema constraints...")
    setup_constraints()

    query = "cs.AI,cs.LG,cs.CL"
    print(f"\nFetching up to {max_papers} papers from ArXiv (last {days_back} days)...")
    papers = await fetch_arxiv(query, max_results=max_papers, days_back=days_back)
    print(f"Fetched {len(papers)} papers.\n")

    resolver = EntityResolver(threshold=0.85)
    # Skip Redis persistence for the seed script — in-memory resolver is fine
    # for a single-run seed operation.

    success = already_done = failed = 0
    quota_hit = False

    for i, paper in enumerate(papers, 1):
        print(f"[{i}/{len(papers)}] {paper['title'][:72]}...")
        processed = False
        try:
            processed = await process_document(paper, WORKSPACE_ID, resolver)
            if processed:
                success += 1
            else:
                already_done += 1
                print("  already ingested, skipped")
        except DailyQuotaExhausted:
            print(
                "\nGemini daily quota exhausted. Re-run tomorrow (or after the quota "
                "resets) to continue — already-processed papers are skipped automatically."
            )
            quota_hit = True
            break
        except Exception as e:
            print(f"  SKIP: {e}")
            failed += 1

        if processed and i < len(papers):
            await asyncio.sleep(RATE_LIMIT_DELAY)

    # Mark the matching source records as success in Postgres (if they exist)
    try:
        _mark_sources_done(query)
    except Exception as e:
        print(f"  (Could not update source status in Postgres: {e})")

    print(f"\n{'='*60}")
    status = "STOPPED (daily quota hit)" if quota_hit else "Ingestion complete"
    print(
        f"{status}: {success} newly ingested, {already_done} already done, {failed} failed"
    )
    print(f"Remaining for next run: {len(papers) - success - already_done - failed}")
    print(f"Neo4j nodes  : {await get_node_count()}")
    print(f"Neo4j edges  : {await get_edge_count()}")
    print(f"Chroma chunks: {await get_chunk_count(WORKSPACE_ID)}")
    print(f"\nExplore the graph: http://localhost:7474")
    print(f"  MATCH (n) RETURN count(n)")
    print(f"  MATCH (p:Paper)<-[:AUTHORED]-(a:Person) RETURN p.name, collect(a.name) LIMIT 5")


def _mark_sources_done(categories_query: str) -> None:
    """Update Postgres source records that match the seeded categories."""
    from datetime import datetime, timezone
    from backend.db.postgres import SessionLocal
    from backend.db.models import Source

    # Use the sync engine — this helper runs in a sync context
    db = SessionLocal()
    try:
        categories = [c.strip() for c in categories_query.split(",") if c.strip()]
        for cat in categories:
            source = (
                db.query(Source)
                .filter(Source.workspace_id == WORKSPACE_ID, Source.url == cat)
                .first()
            )
            if source and source.status in ("pending", "running"):
                source.status = "success"
                source.last_fetched = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=500, help="Max papers to ingest")
    parser.add_argument("--days", type=int, default=90, help="How many days back to fetch")
    args = parser.parse_args()

    close_driver()   # ensure clean state
    asyncio.run(_seed(args.max, args.days))
    close_driver()


if __name__ == "__main__":
    main()
