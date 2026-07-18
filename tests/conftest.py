"""Corpus — test suite configuration and shared fixtures."""

from __future__ import annotations

import pytest


def _ollama_reachable() -> bool:
    import httpx

    from src.config import get_settings

    try:
        resp = httpx.get(f"{get_settings().ollama.host}/api/tags", timeout=2.0)
        return resp.status_code == 200
    except Exception:
        return False


def pytest_collection_modifyitems(config, items):
    """Auto-skip requires_ollama tests when no Ollama server is reachable."""
    marked = [item for item in items if item.get_closest_marker("requires_ollama")]
    if not marked:
        return
    if not _ollama_reachable():
        skip = pytest.mark.skip(reason="Ollama server not reachable")
        for item in marked:
            item.add_marker(skip)


@pytest.fixture
def app_settings():
    """Provide test settings with defaults overridden for testing."""
    import os

    os.environ.setdefault("DEBUG", "true")
    os.environ.setdefault("ENVIRONMENT", "test")
    os.environ.setdefault("POSTGRES_DATABASE_URL", "postgresql+psycopg2://test:test@localhost:5432/test_db")
    os.environ.setdefault("OPENSEARCH__HOST", "http://localhost:9200")
    os.environ.setdefault("REDIS__HOST", "localhost")

    from src.config import Settings

    return Settings()
