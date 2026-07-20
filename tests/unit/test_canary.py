"""Corpus — Canary Probe Unit Tests."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.canary import get_last_canary, run_canary_once


@pytest.mark.asyncio
async def test_run_canary_once_healthy_when_retrieval_and_llm_both_succeed():
    """A healthy stack: retrieval returns chunks, the LLM ping returns no error."""
    app_state = MagicMock()
    app_state.opensearch = MagicMock()
    app_state.redis = AsyncMock()

    fake_search_service = AsyncMock()
    fake_search_service.search.return_value = [{"chunk_id": "c1"}, {"chunk_id": "c2"}]

    fake_llm_response = MagicMock()
    fake_llm_response.raise_for_status.return_value = None
    fake_llm_response.json.return_value = {"response": "p"}

    with (
        patch("src.retrieval.hybrid_search.HybridSearchService", return_value=fake_search_service),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_client = AsyncMock()
        mock_client.post.return_value = fake_llm_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await run_canary_once(app_state)

    assert result["retrieval_ok"] is True
    assert result["llm_ok"] is True
    assert result["healthy"] is True
    app_state.redis.set.assert_called_once()
    stored_key, stored_payload = app_state.redis.set.call_args[0]
    assert stored_key == "corpus:canary:last"
    assert json.loads(stored_payload)["healthy"] is True


@pytest.mark.asyncio
async def test_run_canary_once_unhealthy_when_retrieval_returns_nothing():
    """Zero retrieved chunks marks the probe unhealthy even if the LLM responds fine —
    /health/canary must catch a broken index even when the LLM itself is up."""
    app_state = MagicMock()
    app_state.opensearch = MagicMock()
    app_state.redis = AsyncMock()

    fake_search_service = AsyncMock()
    fake_search_service.search.return_value = []

    fake_llm_response = MagicMock()
    fake_llm_response.raise_for_status.return_value = None
    fake_llm_response.json.return_value = {"response": "p"}

    with (
        patch("src.retrieval.hybrid_search.HybridSearchService", return_value=fake_search_service),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_client = AsyncMock()
        mock_client.post.return_value = fake_llm_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        result = await run_canary_once(app_state)

    assert result["retrieval_ok"] is False
    assert result["healthy"] is False
    assert "0 chunks" in result["detail"]


@pytest.mark.asyncio
async def test_run_canary_once_survives_llm_exception():
    """An unreachable Ollama must not crash the probe — it should report llm_ok=False
    with the exception recorded, not propagate."""
    app_state = MagicMock()
    app_state.opensearch = MagicMock()
    app_state.redis = AsyncMock()

    fake_search_service = AsyncMock()
    fake_search_service.search.return_value = [{"chunk_id": "c1"}]

    with (
        patch("src.retrieval.hybrid_search.HybridSearchService", return_value=fake_search_service),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_client_cls.return_value.__aenter__.side_effect = ConnectionError("Ollama unreachable")

        result = await run_canary_once(app_state)

    assert result["retrieval_ok"] is True
    assert result["llm_ok"] is False
    assert result["healthy"] is False
    assert "Ollama unreachable" in result["detail"]


@pytest.mark.asyncio
async def test_get_last_canary_returns_none_when_missing():
    """No canary has run yet — get_last_canary must return None, not raise."""
    redis = AsyncMock()
    redis.get.return_value = None
    assert await get_last_canary(redis) is None


@pytest.mark.asyncio
async def test_get_last_canary_survives_redis_error():
    """A Redis outage while reading the canary result must not break /health/canary."""
    redis = AsyncMock()
    redis.get.side_effect = ConnectionError("redis down")
    assert await get_last_canary(redis) is None
