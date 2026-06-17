#!/usr/bin/env python3
"""Retroactively scan the existing graph for conflicting claims between sources."""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from backend.db.neo4j import close_driver
from backend.ingestion.conflict_detector import detect_all_conflicts

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default="arxiv_seed")
    args = parser.parse_args()

    count = detect_all_conflicts(args.workspace)
    print(f"Conflicting node pairs found and flagged: {count}")
    close_driver()
