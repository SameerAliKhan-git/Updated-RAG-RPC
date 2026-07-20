"""Corpus — FastAPI dependency injection."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy.orm import Session

from src.config import Settings, get_settings


def get_db_session(request: Request) -> Iterator[Session]:
    """Yield a SQLAlchemy session from the app's session factory."""
    session_factory = request.app.state.db_session_factory
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def get_opensearch(request: Request):
    """Get the shared OpenSearch client."""
    return request.app.state.opensearch


async def get_redis(request: Request) -> Redis:
    """Get the shared async Redis client."""
    return request.app.state.redis


def get_app_settings() -> Settings:
    """Dependency wrapper around settings singleton."""
    return get_settings()
