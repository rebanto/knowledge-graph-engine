import os
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError
from dotenv import load_dotenv

from backend.core.resilience import gemini_breaker, CircuitBreakerError
from backend.core.observability import llm_calls_total

load_dotenv()

MODEL = os.environ.get("LLM_MODEL", "gemini-flash-lite-latest")

# Bulkhead: dedicated thread pool for LLM I/O so it can't starve the DB pools.
_llm_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="llm")

_client = None


class DailyQuotaExhausted(Exception):
    """Raised when the Gemini free-tier per-day request quota is hit."""


def get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def _call_sync(prompt: str, json_mode: bool, retries: int = 2):
    """Synchronous Gemini call with retry logic — runs in the LLM thread pool."""
    config = types.GenerateContentConfig(response_mime_type="application/json") if json_mode else None
    last_err = None
    for attempt in range(retries + 1):
        try:
            gemini_breaker.call(lambda: None)  # check circuit is closed first
            result = get_client().models.generate_content(
                model=MODEL, contents=prompt, config=config
            )
            llm_calls_total.labels(operation="generate", status="ok").inc()
            return result
        except CircuitBreakerError:
            llm_calls_total.labels(operation="generate", status="circuit_open").inc()
            raise
        except ClientError as e:
            if "PerDay" in str(e):
                llm_calls_total.labels(operation="generate", status="quota").inc()
                raise DailyQuotaExhausted(str(e)) from e
            llm_calls_total.labels(operation="generate", status="client_error").inc()
            raise
        except ServerError as e:
            last_err = e
            llm_calls_total.labels(operation="generate", status="server_error").inc()
            if attempt < retries:
                import time
                import random
                time.sleep(min(2 ** attempt + random.random(), 10))
            continue
    raise last_err


async def _call_async(prompt: str, json_mode: bool) -> object:
    """Run the Gemini call in the LLM bulkhead thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _llm_executor, _call_sync, prompt, json_mode
    )


async def generate_json(prompt: str) -> dict:
    response = await _call_async(prompt, json_mode=True)
    try:
        return json.loads(response.text)
    except (json.JSONDecodeError, AttributeError):
        return {}


async def generate_text(prompt: str) -> str:
    response = await _call_async(prompt, json_mode=False)
    return (response.text or "").strip()


# ── Streaming generation (for SSE endpoint) ────────────────────────────────────

def _stream_sync(prompt: str):
    """Yields text chunks from a streaming Gemini generation."""
    try:
        gemini_breaker.call(lambda: None)
    except CircuitBreakerError:
        yield "[Service temporarily unavailable — please retry]"
        return

    for chunk in get_client().models.generate_content_stream(model=MODEL, contents=prompt):
        if chunk.text:
            yield chunk.text


async def generate_text_stream(prompt: str):
    """Async generator that yields text chunks from Gemini streaming API."""
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()

    def _producer():
        try:
            for chunk in _stream_sync(prompt):
                # thread-safe: put_nowait is safe from non-async threads
                asyncio.run_coroutine_threadsafe(queue.put(chunk), loop)
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(sentinel), loop)

    loop.run_in_executor(_llm_executor, _producer)

    while True:
        item = await queue.get()
        if item is sentinel:
            break
        yield item
