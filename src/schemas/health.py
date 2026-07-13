"""Corpus — Health check response schemas."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class ServiceStatus(StrEnum):
    """Status of an individual service dependency."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"


class OverallStatus(StrEnum):
    """Overall system health status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ServiceHealth(BaseModel):
    """Health status for a single service."""

    name: str
    status: ServiceStatus
    latency_ms: float | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    """Full health check response."""

    status: OverallStatus
    version: str
    environment: str
    services: list[ServiceHealth]
