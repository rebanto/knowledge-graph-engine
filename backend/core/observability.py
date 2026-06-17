import os
import time
import uuid
import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST  # noqa: F401 — re-exported

# ── Structlog configuration ────────────────────────────────────────────────────
_LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger()

# ── Prometheus metrics ─────────────────────────────────────────────────────────
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)
http_request_duration = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["path"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)
llm_calls_total = Counter(
    "llm_calls_total",
    "Total LLM API calls",
    ["operation", "status"],
)
cache_hits_total = Counter(
    "cache_hits_total",
    "Cache hit count by cache name",
    ["cache"],
)
cache_misses_total = Counter(
    "cache_misses_total",
    "Cache miss count by cache name",
    ["cache"],
)
ingestion_queue_depth = Gauge(
    "ingestion_queue_depth",
    "Current number of jobs in the ingestion queue",
)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Injects X-Request-ID into every request and structlog context."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        path = request.url.path
        http_requests_total.labels(
            method=request.method,
            path=path,
            status=response.status_code,
        ).inc()
        http_request_duration.labels(path=path).observe(duration)

        response.headers["X-Request-ID"] = request_id
        return response


async def metrics_endpoint(request: Request) -> Response:
    """Expose Prometheus metrics at GET /metrics."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
