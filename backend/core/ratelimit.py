"""Shared slowapi rate limiter.

Lives in its own module (not main.py) so route modules can import it without a
circular import. Limits protect the expensive LLM-backed endpoints from a
runaway client burning the Gemini quota — one browser tab polling in a loop can
otherwise exhaust the free tier for the whole instance.

Disable entirely (e.g. for load tests) with RATE_LIMIT_ENABLED=false.
"""
import os

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    enabled=os.environ.get("RATE_LIMIT_ENABLED", "true").lower() != "false",
)

# Per-endpoint budgets, kept in one place so they're easy to tune.
QUESTION_LIMIT = os.environ.get("RATE_LIMIT_QUESTION", "30/minute")
DEEP_RESEARCH_LIMIT = os.environ.get("RATE_LIMIT_DEEP_RESEARCH", "6/minute")
SOURCE_MUTATION_LIMIT = os.environ.get("RATE_LIMIT_SOURCE_MUTATION", "30/minute")
