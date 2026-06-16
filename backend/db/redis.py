import os
import json
import hashlib
import redis
from dotenv import load_dotenv

load_dotenv()

_client = None


def get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    return _client


def _cache_key(workspace_id: str, question: str) -> str:
    normalized = f"{workspace_id}:{question.strip().lower()}"
    return "qa:" + hashlib.sha256(normalized.encode()).hexdigest()


def get_cached_answer(workspace_id: str, question: str) -> dict | None:
    raw = get_client().get(_cache_key(workspace_id, question))
    return json.loads(raw) if raw else None


def set_cached_answer(workspace_id: str, question: str, result: dict, ttl: int = 3600) -> None:
    get_client().set(_cache_key(workspace_id, question), json.dumps(result), ex=ttl)
