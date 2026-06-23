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

# Hard ceiling on a single Gemini call. The google-genai SDK has no built-in
# timeout on generate_content; without this a hung HTTP call blocks an LLM
# thread-pool worker forever, which wedges entity extraction, which leaves the
# ingestion job's asyncio.gather pending and the source stranded at 'running'.
# On timeout the call surfaces as a normal failure (caught per-document) so the
# job still reaches a terminal state.
_LLM_CALL_TIMEOUT = float(os.environ.get("LLM_CALL_TIMEOUT", 90))

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
            # NOTE: deliberately NOT routing the real call through the breaker.
            # Entity extraction fires several windows concurrently per document,
            # so transient 429s/503s arrive in bursts; counting each toward the
            # breaker trips it open and cascades every in-flight document to
            # failure. The per-call retry loop below already absorbs transient
            # ServerErrors, which is the right granularity here.
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
    """Run the Gemini call in the LLM bulkhead thread pool, bounded by a timeout.

    The timeout converts an indefinitely-hung SDK call into a TimeoutError that
    propagates like any other failure, so the ingestion job can finish and reach
    a terminal status instead of hanging at 'running'.
    """
    loop = asyncio.get_event_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(_llm_executor, _call_sync, prompt, json_mode),
        timeout=_LLM_CALL_TIMEOUT,
    )


async def generate_json(prompt: str) -> dict:
    response = await _call_async(prompt, json_mode=True)
    try:
        return json.loads(response.text)
    except (json.JSONDecodeError, AttributeError):
        return {}


# ── Document OCR (scanned/image-only PDFs) ─────────────────────────────────────

_OCR_PROMPT = (
    "Transcribe ALL text from this document exactly, preserving reading order. "
    "Return only the transcribed text — no commentary, no markdown. "
    "If the document contains no readable text at all, return an empty response."
)
# OCR of a multi-page scan can take longer than a normal text call.
_OCR_TIMEOUT = float(os.environ.get("LLM_OCR_TIMEOUT", 180))


def _ocr_pdf_sync(pdf_bytes: bytes) -> str:
    """Send the raw PDF to Gemini (multimodal) and return the transcribed text."""
    gemini_breaker.call(lambda: None)  # honour the circuit breaker
    part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
    resp = get_client().models.generate_content(model=MODEL, contents=[part, _OCR_PROMPT])
    llm_calls_total.labels(operation="ocr", status="ok").inc()
    return (resp.text or "").strip()


async def ocr_pdf(pdf_bytes: bytes) -> str:
    """Async OCR fallback for PDFs that have no extractable text layer."""
    loop = asyncio.get_event_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(_llm_executor, _ocr_pdf_sync, pdf_bytes),
        timeout=_OCR_TIMEOUT,
    )


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
