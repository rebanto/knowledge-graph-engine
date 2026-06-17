import asyncio
import functools
import logging

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
    before_sleep_log,
)
from pybreaker import CircuitBreaker, CircuitBreakerError  # noqa: F401

logger = logging.getLogger(__name__)

# Circuit breakers — one per external dependency, shared across all requests.
# Opens after fail_max failures within the tracking window; half-opens after
# reset_timeout seconds to probe recovery.
gemini_breaker = CircuitBreaker(fail_max=5, reset_timeout=30, name="gemini")
neo4j_breaker = CircuitBreaker(fail_max=5, reset_timeout=30, name="neo4j")
external_breaker = CircuitBreaker(fail_max=3, reset_timeout=60, name="external_http")


def with_retry(
    exception_types: tuple = (Exception,),
    attempts: int = 3,
    initial: float = 0.5,
    max_wait: float = 10.0,
):
    """Decorator: retry an async function with exponential backoff + full jitter."""
    def decorator(fn):
        @retry(
            stop=stop_after_attempt(attempts),
            wait=wait_exponential_jitter(initial=initial, max=max_wait),
            retry=retry_if_exception_type(exception_types),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            return await fn(*args, **kwargs)

        @retry(
            stop=stop_after_attempt(attempts),
            wait=wait_exponential_jitter(initial=initial, max=max_wait),
            retry=retry_if_exception_type(exception_types),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        @functools.wraps(fn)
        def sync_wrapper(*args, **kwargs):
            return fn(*args, **kwargs)

        if asyncio.iscoroutinefunction(fn):
            return async_wrapper
        return sync_wrapper

    return decorator
