"""Corpus — Health endpoint unit tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_app():
    """Create a test app with mocked dependencies."""
    # Patch the lifespan to skip real connections
    from contextlib import asynccontextmanager

    from fastapi import FastAPI

    from src.routers.health import router

    @asynccontextmanager
    async def mock_lifespan(app: FastAPI):
        # Set up mock state
        app.state.db_session_factory = MagicMock()
        app.state.opensearch = MagicMock()
        app.state.redis = AsyncMock()
        yield

    app = FastAPI(lifespan=mock_lifespan)
    app.include_router(router, prefix="/api/v1")
    return app


@pytest.fixture
def client(mock_app):
    """Create a TestClient for the mock app."""
    return TestClient(mock_app)


class TestHealthEndpoint:
    """Tests for GET /api/v1/health."""

    def test_health_returns_200(self, client):
        """Health endpoint should return 200 even when services are degraded."""
        response = client.get("/api/v1/health")
        assert response.status_code == 200

    def test_health_response_shape(self, client):
        """Health response should contain required fields."""
        response = client.get("/api/v1/health")
        data = response.json()

        assert "status" in data
        assert "version" in data
        assert "environment" in data
        assert "services" in data
        assert isinstance(data["services"], list)

    def test_health_reports_all_services(self, client):
        """Health response should report on all infrastructure services."""
        response = client.get("/api/v1/health")
        data = response.json()

        service_names = {s["name"] for s in data["services"]}
        assert "postgres" in service_names
        assert "opensearch" in service_names
        assert "redis" in service_names
        assert "ollama" in service_names

    def test_health_version(self, client):
        """Health response should contain the app version."""
        response = client.get("/api/v1/health")
        data = response.json()
        assert data["version"] == "0.1.0"

    def test_health_service_has_status(self, client):
        """Each service should have a status field."""
        response = client.get("/api/v1/health")
        data = response.json()

        for service in data["services"]:
            assert "status" in service
            assert service["status"] in ("healthy", "unhealthy", "degraded")
