"""Corpus — dead-letter record unit tests."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.services.deadletter import DEADLETTER_KEY, list_failed_jobs, record_failed_job


@pytest.mark.asyncio
async def test_record_failed_job_pushes_and_caps():
    redis = AsyncMock()
    await record_failed_job(redis, "ingest_single_paper_task", "1706.03762", "boom")

    redis.lpush.assert_awaited_once()
    key, payload = redis.lpush.call_args[0]
    assert key == DEADLETTER_KEY
    entry = json.loads(payload)
    assert entry["job"] == "ingest_single_paper_task"
    assert entry["target"] == "1706.03762"
    assert entry["error"] == "boom"
    # capped via ltrim
    redis.ltrim.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_failed_job_never_raises_on_redis_error():
    """Dead-lettering must not mask the original failure it's recording."""
    redis = AsyncMock()
    redis.lpush.side_effect = ConnectionError("redis down")
    # Should not raise
    await record_failed_job(redis, "job", "target", "err")


@pytest.mark.asyncio
async def test_list_failed_jobs_parses_entries():
    redis = AsyncMock()
    redis.lrange.return_value = [
        json.dumps({"job": "j", "target": "1", "error": "e", "ts": 1.0}),
    ]
    jobs = await list_failed_jobs(redis)
    assert jobs[0]["target"] == "1"


@pytest.mark.asyncio
async def test_list_failed_jobs_returns_empty_on_error():
    redis = AsyncMock()
    redis.lrange.side_effect = ConnectionError("down")
    assert await list_failed_jobs(redis) == []
