"""Corpus — Health check router.

GET /api/v1/health — checks connectivity to Postgres, OpenSearch,
Redis, and Ollama. Returns per-service status and overall health.
"""

from __future__ import annotations

import time

import httpx
import structlog
from fastapi import APIRouter, Request
from sqlalchemy import text

from src.config import get_settings
from src.schemas.health import HealthResponse, OverallStatus, ServiceHealth, ServiceStatus

logger = structlog.get_logger(__name__)
router = APIRouter()


async def _check_postgres(request: Request) -> ServiceHealth:
    """Check PostgreSQL connectivity."""
    start = time.monotonic()
    try:
        session_factory = request.app.state.db_session_factory
        session = session_factory()
        try:
            session.execute(text("SELECT 1"))
            latency = (time.monotonic() - start) * 1000
            return ServiceHealth(name="postgres", status=ServiceStatus.HEALTHY, latency_ms=round(latency, 2))
        finally:
            session.close()
    except Exception as e:
        latency = (time.monotonic() - start) * 1000
        logger.warning("health.postgres.failed", error=str(e))
        return ServiceHealth(
            name="postgres", status=ServiceStatus.UNHEALTHY, latency_ms=round(latency, 2), error=str(e)
        )


async def _check_opensearch(request: Request) -> ServiceHealth:
    """Check OpenSearch connectivity."""
    start = time.monotonic()
    try:
        os_client = request.app.state.opensearch
        info = os_client.cluster.health()
        latency = (time.monotonic() - start) * 1000
        cluster_status = info.get("status", "unknown")
        status = ServiceStatus.HEALTHY if cluster_status in ("green", "yellow") else ServiceStatus.DEGRADED
        return ServiceHealth(name="opensearch", status=status, latency_ms=round(latency, 2))
    except Exception as e:
        latency = (time.monotonic() - start) * 1000
        logger.warning("health.opensearch.failed", error=str(e))
        return ServiceHealth(
            name="opensearch", status=ServiceStatus.UNHEALTHY, latency_ms=round(latency, 2), error=str(e)
        )


async def _check_redis(request: Request) -> ServiceHealth:
    """Check Redis connectivity."""
    start = time.monotonic()
    try:
        redis_client = request.app.state.redis
        await redis_client.ping()
        latency = (time.monotonic() - start) * 1000
        return ServiceHealth(name="redis", status=ServiceStatus.HEALTHY, latency_ms=round(latency, 2))
    except Exception as e:
        latency = (time.monotonic() - start) * 1000
        logger.warning("health.redis.failed", error=str(e))
        return ServiceHealth(name="redis", status=ServiceStatus.UNHEALTHY, latency_ms=round(latency, 2), error=str(e))


async def _check_ollama() -> ServiceHealth:
    """Check Ollama LLM server connectivity."""
    settings = get_settings()
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ollama.host}/api/tags")
            latency = (time.monotonic() - start) * 1000
            if resp.status_code == 200:
                return ServiceHealth(name="ollama", status=ServiceStatus.HEALTHY, latency_ms=round(latency, 2))
            return ServiceHealth(
                name="ollama",
                status=ServiceStatus.DEGRADED,
                latency_ms=round(latency, 2),
                error=f"HTTP {resp.status_code}",
            )
    except Exception as e:
        latency = (time.monotonic() - start) * 1000
        logger.warning("health.ollama.failed", error=str(e))
        return ServiceHealth(name="ollama", status=ServiceStatus.UNHEALTHY, latency_ms=round(latency, 2), error=str(e))


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request) -> HealthResponse:
    """System health check endpoint.

    Checks connectivity to all infrastructure dependencies and returns
    per-service status with latency measurements.
    """
    settings = get_settings()

    # Run all health checks
    services = [
        await _check_postgres(request),
        await _check_opensearch(request),
        await _check_redis(request),
        await _check_ollama(),
    ]

    # Determine overall status
    statuses = [s.status for s in services]
    if all(s == ServiceStatus.HEALTHY for s in statuses):
        overall = OverallStatus.HEALTHY
    elif any(s == ServiceStatus.UNHEALTHY for s in statuses):
        overall = OverallStatus.DEGRADED
    else:
        overall = OverallStatus.DEGRADED

    return HealthResponse(
        status=overall,
        version="0.1.0",
        environment=settings.environment,
        services=services,
    )


@router.get("/health/canary", summary="Last synthetic canary probe result")
async def canary_status(request: Request):
    """Return the most recent hourly canary verdict (retrieval + LLM exercised for real)."""
    from src.services.canary import get_last_canary

    result = await get_last_canary(request.app.state.redis)
    if result is None:
        return {"status": "not_run_yet", "healthy": None}
    return {"status": "ok" if result.get("healthy") else "failing", **result}


@router.get("/health/dead-letter", summary="Recent failed background jobs")
async def dead_letter(request: Request):
    """Failed ingestion jobs the arq worker recorded — re-trigger via
    POST /papers/{arxiv_id}/ingest once the cause is fixed."""
    from src.services.deadletter import list_failed_jobs

    jobs = await list_failed_jobs(request.app.state.redis)
    return {"count": len(jobs), "jobs": jobs}


@router.delete("/health/dead-letter", summary="Clear the dead-letter list")
async def clear_dead_letter(request: Request):
    from src.services.deadletter import clear_failed_jobs

    await clear_failed_jobs(request.app.state.redis)
    return {"status": "cleared"}
