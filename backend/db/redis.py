import os
import json
import hashlib
import base64
import asyncio
from typing import Optional
import numpy as np
import redis.asyncio as aioredis
from redis import Redis  # sync client, used by RQ queue
from dotenv import load_dotenv

load_dotenv()

_async_client: Optional[aioredis.Redis] = None

# Cache TTLs — configurable via env
TTL_ANSWERS = int(os.environ.get("CACHE_TTL_ANSWERS", 3600))
TTL_ROUTE   = int(os.environ.get("CACHE_TTL_ROUTE",   86400))
TTL_CYPHER  = int(os.environ.get("CACHE_TTL_CYPHER",  300))
TTL_EMBED   = int(os.environ.get("CACHE_TTL_EMBED",   604800))  # 7 days
TTL_INFLUENCE = int(os.environ.get("CACHE_TTL_INFLUENCE", 300))  # PageRank/communities


def get_async_client() -> aioredis.Redis:
    global _async_client
    if _async_client is None:
        _async_client = aioredis.from_url(
            os.environ["REDIS_URL"],
            decode_responses=True,
            max_connections=50,
        )
    return _async_client


async def close_async_client() -> None:
    """Close the module-global async Redis client and reset it to None.

    Required by the RQ SimpleWorker, which runs every job via a fresh
    asyncio.run() (one event loop per job). A redis.asyncio client binds its
    connection pool to the loop that created it; if it isn't closed before that
    loop is torn down, the NEXT job's loop reuses the stale pool and fails with
    "RuntimeError: Event loop is closed". Resetting to None forces a fresh
    client (bound to the new loop) on the next get_async_client() call.
    """
    global _async_client
    if _async_client is not None:
        try:
            await _async_client.aclose()
        finally:
            _async_client = None


def _key(namespace: str, *parts: str) -> str:
    normalized = ":".join(parts).strip().lower()
    return f"{namespace}:{hashlib.sha256(normalized.encode()).hexdigest()}"


# ── Answer cache ───────────────────────────────────────────────────────────────

async def get_cached_answer(workspace_id: str, question: str) -> Optional[dict]:
    raw = await get_async_client().get(_key("qa", workspace_id, question))
    return json.loads(raw) if raw else None


async def set_cached_answer(workspace_id: str, question: str, result: dict) -> None:
    await get_async_client().set(
        _key("qa", workspace_id, question),
        json.dumps(result),
        ex=TTL_ANSWERS,
    )


# ── Route classification cache ─────────────────────────────────────────────────

async def get_cached_route(workspace_id: str, question: str) -> Optional[dict]:
    raw = await get_async_client().get(_key("route", workspace_id, question))
    return json.loads(raw) if raw else None


async def set_cached_route(workspace_id: str, question: str, result: dict) -> None:
    await get_async_client().set(
        _key("route", workspace_id, question),
        json.dumps(result),
        ex=TTL_ROUTE,
    )


# ── Cypher result cache ────────────────────────────────────────────────────────

async def get_cached_cypher(cypher: str) -> Optional[list]:
    raw = await get_async_client().get(_key("cypher", cypher))
    return json.loads(raw) if raw else None


async def set_cached_cypher(cypher: str, records: list) -> None:
    await get_async_client().set(
        _key("cypher", cypher),
        json.dumps(records, default=str),
        ex=TTL_CYPHER,
    )


# ── Embedding cache ────────────────────────────────────────────────────────────

async def get_cached_embedding(text: str) -> Optional[list]:
    raw = await get_async_client().get(_key("embed", text))
    if raw is None:
        return None
    arr = np.frombuffer(base64.b64decode(raw), dtype=np.float32)
    return arr.tolist()


async def set_cached_embedding(text: str, embedding: list) -> None:
    arr = np.array(embedding, dtype=np.float32)
    encoded = base64.b64encode(arr.tobytes()).decode("ascii")
    await get_async_client().set(_key("embed", text), encoded, ex=TTL_EMBED)


# ── Graph-algorithm cache (PageRank influence / communities) ───────────────────
# Whole-workspace PageRank and community detection pull the entire subgraph into
# networkx — too heavy to run on every question. The result changes only when the
# graph does, so it is cached per (workspace, kind) and swept on new ingestion
# (see invalidate_workspace_caches). `kind` is "influence" or "communities".

async def get_cached_graph_algo(workspace_id: str, kind: str) -> Optional[list]:
    raw = await get_async_client().get(_key("influence", workspace_id, kind))
    return json.loads(raw) if raw else None


async def set_cached_graph_algo(workspace_id: str, kind: str, result: list) -> None:
    await get_async_client().set(
        _key("influence", workspace_id, kind),
        json.dumps(result, default=str),
        ex=TTL_INFLUENCE,
    )


# ── In-flight request deduplication ───────────────────────────────────────────

async def acquire_inflight_lock(workspace_id: str, question: str) -> bool:
    """Return True if this caller acquired the lock (i.e., should process the request)."""
    lock_key = _key("inflight", workspace_id, question)
    return bool(await get_async_client().set(lock_key, "1", nx=True, ex=60))


async def release_inflight_lock(workspace_id: str, question: str) -> None:
    await get_async_client().delete(_key("inflight", workspace_id, question))


async def wait_for_inflight(workspace_id: str, question: str, timeout: int = 55) -> Optional[dict]:
    """Poll for a cached answer while another request is processing the same question."""
    ans_key = _key("qa", workspace_id, question)
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        raw = await get_async_client().get(ans_key)
        if raw:
            return json.loads(raw)
        await asyncio.sleep(0.2)
    return None


# ── Entity resolver persistence (cross-source dedup) ──────────────────────────

async def load_resolver_registry(workspace_id: str, entity_type: str) -> dict[str, np.ndarray]:
    """Load persisted entity embeddings for a workspace+type from Redis."""
    key = f"resolver:{workspace_id}:{entity_type}"
    raw = await get_async_client().hgetall(key)
    result = {}
    for name, encoded in raw.items():
        result[name] = np.frombuffer(base64.b64decode(encoded), dtype=np.float32)
    return result


async def flush_resolver_registry(
    workspace_id: str, entity_type: str, registry: dict[str, np.ndarray]
) -> None:
    """Persist entity embeddings for a workspace+type to Redis."""
    if not registry:
        return
    key = f"resolver:{workspace_id}:{entity_type}"
    mapping = {
        name: base64.b64encode(emb.astype(np.float32).tobytes()).decode("ascii")
        for name, emb in registry.items()
    }
    await get_async_client().hset(key, mapping=mapping)
    await get_async_client().expire(key, 86400 * 30)  # 30 days


# ── Cache invalidation ─────────────────────────────────────────────────────────

async def invalidate_workspace_caches(workspace_id: str) -> None:
    """Delete route, Cypher, and any legacy answer caches after new ingestion."""
    client = get_async_client()
    # SCAN instead of KEYS so we don't block Redis on large keyspaces.
    # qa:* is swept defensively — answer caching is disabled, but old entries
    # written before that change would otherwise be served stale indefinitely.
    # influence:* holds cached PageRank/community results, now stale after new data.
    for pattern in ["route:*", "cypher:*", "qa:*", "influence:*"]:
        cursor = 0
        while True:
            cursor, keys = await client.scan(cursor, match=pattern, count=200)
            if keys:
                await client.delete(*keys)
            if cursor == 0:
                break


# ── Checkpoint tracking (ingestion) ───────────────────────────────────────────

async def get_checkpoint(source_id: str) -> Optional[str]:
    return await get_async_client().get(f"checkpoint:{source_id}")


async def set_checkpoint(source_id: str, document_url: str) -> None:
    await get_async_client().set(f"checkpoint:{source_id}", document_url, ex=86400 * 7)


async def clear_checkpoint(source_id: str) -> None:
    await get_async_client().delete(f"checkpoint:{source_id}")


# ── Sync client for RQ queue (RQ requires a non-async Redis connection) ────────

_sync_client: Optional[Redis] = None


def get_sync_client() -> Redis:
    global _sync_client
    if _sync_client is None:
        _sync_client = Redis.from_url(os.environ["REDIS_URL"])
    return _sync_client
