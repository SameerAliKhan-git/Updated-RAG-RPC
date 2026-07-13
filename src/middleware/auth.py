"""Corpus — API Key Authentication Middleware.

Enforces API key auth on all endpoints via X-API-Key header.
Skipped in debug mode for development convenience.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from src.config import get_settings

logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    request: Request,
    api_key: str | None = Security(api_key_header),
) -> str | None:
    """FastAPI dependency — verify the API key from the X-API-Key header.

    In debug mode (ENVIRONMENT=development, DEBUG=true), auth is skipped.
    """
    settings = get_settings()

    # Skip auth in development
    if settings.debug and settings.environment == "development":
        return "dev-mode"

    # If no API key configured, skip auth (but warn)
    if not settings.api_key:
        logger.warning("No API_KEY configured — all requests are unauthenticated.")
        return "no-auth"

    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Provide it via the X-API-Key header.",
        )

    if api_key != settings.api_key:
        raise HTTPException(
            status_code=403,
            detail="Invalid API key.",
        )

    return api_key
