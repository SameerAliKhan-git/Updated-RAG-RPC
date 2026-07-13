"""Corpus — Redis Services Unit Tests."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.redis_services import RedisServicesManager


@pytest.mark.asyncio
async def test_session_memory_get_set():
    """Verify that SessionMemory gets and sets conversation histories."""
    mock_redis = AsyncMock()
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    mock_redis.get.return_value = json.dumps(history)

    manager = RedisServicesManager(mock_redis)

    # 1. Test get
    res = await manager.get_session_history("session_123")
    assert res == history
    mock_redis.get.assert_called_once_with("corpus:session:session_123")

    # 2. Test set
    await manager.save_session_history("session_123", history, ttl_hours=2)
    mock_redis.setex.assert_called_once_with(
        "corpus:session:session_123",
        7200,
        json.dumps(history),
    )


@pytest.mark.asyncio
async def test_semantic_cache_hit_and_miss():
    """Verify semantic cache query evaluation matches above threshold and misses below."""
    mock_redis = AsyncMock()

    # Cached embedding matching a query exactly
    cached_entry = {
        "query": "cached query",
        "embedding": [0.5, 0.5, 0.0, 0.0],
        "response": {"answer_markdown": "cached answer"}
    }

    mock_redis.keys.return_value = ["corpus:semcache:uuid1"]
    mock_redis.get.return_value = json.dumps(cached_entry)

    manager = RedisServicesManager(mock_redis)

    # 1. Check matching embedding (cosine similarity = 1.0)
    query_emb = [0.5, 0.5, 0.0, 0.0]
    hit = await manager.get_semantic_cache(query_emb, threshold=0.95)
    assert hit == {"answer_markdown": "cached answer"}

    # 2. Check orthogonal embedding (cosine similarity = 0.0)
    orth_emb = [0.0, 0.0, 0.5, 0.5]
    miss = await manager.get_semantic_cache(orth_emb, threshold=0.95)
    assert miss is None


@pytest.mark.asyncio
@patch("arq.create_pool", new_callable=AsyncMock)
async def test_enqueue_paper_ingestion(mock_arq_pool):
    """Verify that paper ingestion enqueues jobs via arq pool connection."""
    mock_redis = AsyncMock()
    mock_arq_redis = AsyncMock()
    mock_arq_pool.return_value = mock_arq_redis

    manager = RedisServicesManager(mock_redis)
    res = await manager.enqueue_paper_ingestion("1234.5678")

    assert res is True
    mock_arq_pool.assert_called_once()
    mock_arq_redis.enqueue_job.assert_called_once_with("ingest_single_paper_task", "1234.5678")
