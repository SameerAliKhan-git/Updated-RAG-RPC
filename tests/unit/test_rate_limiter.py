"""Corpus — Rate Limiter Unit Tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from src.middleware.rate_limiter import RateLimiter


@pytest.mark.asyncio
@patch("src.middleware.rate_limiter.get_settings")
async def test_rate_limiter_allows_under_limit(mock_get_settings):
    """Verify that RateLimiter allows requests if request count is within limit."""
    mock_settings = MagicMock()
    mock_settings.debug = False
    mock_get_settings.return_value = mock_settings

    mock_redis = MagicMock()
    mock_pipeline = MagicMock()
    # Execute is the only method that needs to be awaited
    mock_pipeline.execute = AsyncMock()
    mock_pipeline.execute.return_value = [0, 0, 5, True]
    mock_redis.pipeline.return_value = mock_pipeline

    mock_request = MagicMock()
    mock_request.app.state.redis = mock_redis
    mock_request.headers = {}
    mock_request.client.host = "127.0.0.1"

    limiter = RateLimiter(requests_per_minute=10)

    # Should not raise exception
    await limiter(mock_request)
    assert mock_redis.pipeline.call_count == 1


@pytest.mark.asyncio
@patch("src.middleware.rate_limiter.get_settings")
async def test_rate_limiter_raises_429_on_exceeded(mock_get_settings):
    """Verify that RateLimiter raises HTTPException(429) if limit is exceeded."""
    mock_settings = MagicMock()
    mock_settings.debug = False
    mock_get_settings.return_value = mock_settings

    mock_redis = MagicMock()
    mock_pipeline = MagicMock()
    # Execute is the only method that needs to be awaited
    mock_pipeline.execute = AsyncMock()
    mock_pipeline.execute.return_value = [0, 0, 12, True]
    mock_redis.pipeline.return_value = mock_pipeline

    mock_request = MagicMock()
    mock_request.app.state.redis = mock_redis
    mock_request.headers = {}
    mock_request.client.host = "127.0.0.1"

    limiter = RateLimiter(requests_per_minute=10)

    with pytest.raises(HTTPException) as exc_info:
        await limiter(mock_request)

    assert exc_info.value.status_code == 429
    assert "Rate limit exceeded" in exc_info.value.detail
