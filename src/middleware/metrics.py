"""Corpus — Prometheus application metrics.

Exposes counters/histograms consumed by the Prometheus scrape job
(prometheus/prometheus.yml → api:8000/metrics) and the Grafana dashboard.
"""

from __future__ import annotations

import time

from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

HTTP_REQUESTS = Counter(
    "corpus_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

HTTP_DURATION = Histogram(
    "corpus_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
)

RAG_STAGE_DURATION = Histogram(
    "corpus_rag_stage_duration_seconds",
    "Duration of each agentic pipeline stage",
    ["stage"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)

SEMANTIC_CACHE_HITS = Counter("corpus_semantic_cache_hits_total", "Semantic cache hits")
SEMANTIC_CACHE_MISSES = Counter("corpus_semantic_cache_misses_total", "Semantic cache misses")

LLM_CALLS = Counter("corpus_llm_calls_total", "LLM completions issued", ["role"])
LLM_TOKENS = Counter("corpus_llm_tokens_total", "LLM completion tokens generated", ["role"])

GUARDRAIL_FLAGS = Counter("corpus_guardrail_flags_total", "Guardrail heuristics triggered", ["flag"])


def _normalize_path(path: str) -> str:
    """Collapse high-cardinality path segments (paper ids) into a template."""
    parts = path.split("/")
    if len(parts) > 4 and parts[3] == "papers" and parts[4] not in ("upload", "extract-metadata", ""):
        parts[4] = "{arxiv_id}"
    return "/".join(parts)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record request counts and latencies for every HTTP call."""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start

        path = _normalize_path(request.url.path)
        HTTP_REQUESTS.labels(method=request.method, path=path, status=str(response.status_code)).inc()
        HTTP_DURATION.labels(method=request.method, path=path).observe(elapsed)
        return response
