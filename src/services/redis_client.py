"""Corpus — Async Redis client wrapper."""

from __future__ import annotations

import redis.asyncio as aioredis

from src.config import RedisSettings


async def create_redis_client(settings: RedisSettings) -> aioredis.Redis:
    """Create an async Redis client.

    Args:
        settings: Redis connection settings.

    Returns:
        Connected async Redis client.
    """
    client = aioredis.Redis(
        host=settings.host,
        port=settings.port,
        password=settings.password or None,
        db=settings.db,
        decode_responses=True,
        socket_timeout=5,
        socket_connect_timeout=5,
        retry_on_timeout=True,
    )
    # Verify connection
    await client.ping()
    return client
