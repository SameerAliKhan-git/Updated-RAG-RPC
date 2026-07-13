"""Corpus — test suite configuration and shared fixtures."""

from __future__ import annotations

import pytest


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
