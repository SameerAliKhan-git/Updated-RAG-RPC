"""Corpus — Redis Services.

Implements all four explicit Redis responsibilities:
1. Conversation/session memory for multi-turn follow-ups.
2. Semantic cache for repeating/near-duplicate questions using query embeddings.
3. Rate limiting (sliding window logic).
4. Async task queue (arq worker pool) for on-demand paper ingestion.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import redis.asyncio as aioredis

from src.config import get_settings

logger = logging.getLogger(__name__)


class RedisServicesManager:
    """Manages Redis-backed application helper services."""

    def __init__(self, redis_client: aioredis.Redis):
        self.redis = redis_client
        self.settings = get_settings()

    # ─── 1. Conversation / Session Memory ──────────────────────────

    async def get_session_history(self, session_id: str) -> List[Dict[str, str]]:
        """Fetch session conversation history."""
        key = f"corpus:session:{session_id}"
        try:
            data = await self.redis.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.error(f"Redis get_session_history failed for {session_id}: {e}")
        return []

    async def save_session_history(
        self, session_id: str, history: List[Dict[str, str]], ttl_hours: int = 6
    ) -> None:
        """Persist session conversation history."""
        key = f"corpus:session:{session_id}"
        try:
            await self.redis.setex(
                key,
                3600 * ttl_hours,
                json.dumps(history),
            )
        except Exception as e:
            logger.error(f"Redis save_session_history failed for {session_id}: {e}")

    # ─── 2. Semantic Cache ──────────────────────────────────────────

    async def get_semantic_cache(
        self, query_embedding: List[float], threshold: float = 0.96
    ) -> Optional[Dict[str, Any]]:
        """Find a cached response with query embedding similarity above threshold.

        Calculates cosine similarity locally in Python over cached keys.
        """
        try:
            # Get list of all cache keys
            keys = await self.redis.keys("corpus:semcache:*")
            if not keys:
                return None

            import math

            def cosine_similarity(v1: List[float], v2: List[float]) -> float:
                dot_product = sum(x * y for x, y in zip(v1, v2))
                norm1 = math.sqrt(sum(x * x for x in v1))
                norm2 = math.sqrt(sum(x * x for x in v2))
                if norm1 == 0 or norm2 == 0:
                    return 0.0
                return dot_product / (norm1 * norm2)

            best_score = -1.0
            best_val = None

            for key in keys:
                # Load metadata
                meta_raw = await self.redis.get(key)
                if not meta_raw:
                    continue
                cache_entry = json.loads(meta_raw)

                cached_embedding = cache_entry.get("embedding")
                if not cached_embedding or len(cached_embedding) != len(query_embedding):
                    continue

                sim = cosine_similarity(query_embedding, cached_embedding)
                if sim > best_score:
                    best_score = sim
                    best_val = cache_entry

            if best_score >= threshold and best_val:
                logger.info(f"Semantic cache hit: similarity {best_score:.4f} >= threshold {threshold}")
                return best_val.get("response")

        except Exception as e:
            logger.error(f"Redis get_semantic_cache failed: {e}")
        return None

    async def set_semantic_cache(
        self,
        query: str,
        query_embedding: List[float],
        response: Dict[str, Any],
        ttl_hours: int = 6,
    ) -> None:
        """Store response in semantic cache mapped to query embedding."""
        import uuid
        cache_id = str(uuid.uuid4())
        key = f"corpus:semcache:{cache_id}"

        entry = {
            "query": query,
            "embedding": query_embedding,
            "response": response,
            "created_at": time.time(),
        }

        try:
            await self.redis.setex(
                key,
                3600 * ttl_hours,
                json.dumps(entry),
            )
            logger.info(f"Saved query to semantic cache: {query[:60]}...")
        except Exception as e:
            logger.error(f"Redis set_semantic_cache failed: {e}")

    # ─── 3. Sliding Window Rate Limiting ────────────────────────────

    async def check_rate_limit(
        self, client_id: str, max_requests: int = 30, window_seconds: int = 60
    ) -> Tuple[bool, int]:
        """Check rate limit using sliding window.

        Returns (is_allowed, retry_after_seconds)
        """
        key = f"corpus:ratelimit:{client_id}"
        now = time.time()
        window_start = now - window_seconds

        try:
            pipe = self.redis.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zadd(key, {str(now): now})
            pipe.zcard(key)
            pipe.expire(key, window_seconds + 10)

            results = await pipe.execute()
            request_count = results[2]

            if request_count > max_requests:
                retry_after = int(window_seconds - (now - window_start))
                return False, max(1, retry_after)

            return True, 0

        except Exception as e:
            logger.error(f"Rate limit check failed: {e}")
            # Permissive default
            return True, 0

    # ─── 4. Async Task Queue (Arq Worker Wrapper) ───────────────────

    async def enqueue_paper_ingestion(self, arxiv_id: str) -> bool:
        """Enqueue an on-demand single-paper ingestion task using arq."""
        try:
            from arq import create_pool
            from arq.connections import RedisSettings as ArqRedisSettings

            # Configure RedisSettings mapping to arq format
            arq_redis = await create_pool(
                ArqRedisSettings(
                    host=self.settings.redis.host,
                    port=self.settings.redis.port,
                    password=self.settings.redis.password or None,
                    database=self.settings.redis.db,
                )
            )
            # Enqueue job to arq worker queue
            job = await arq_redis.enqueue_job("ingest_single_paper_task", arxiv_id)
            await arq_redis.close()
            logger.info(f"Arq: Enqueued job {job.job_id} for paper {arxiv_id}")
            return True
        except ImportError:
            # Fallback to direct Redis list if arq is not installed/imported
            logger.warning("Arq library not imported. Falling back to direct Redis task queue list.")
            return await self._enqueue_list_fallback(arxiv_id)
        except Exception as e:
            logger.error(f"Arq enqueue failed: {e}. Trying list fallback.")
            return await self._enqueue_list_fallback(arxiv_id)

    async def _enqueue_list_fallback(self, arxiv_id: str) -> bool:
        """Fallback task list push if arq pool initialization fails."""
        try:
            task_data = json.dumps({"arxiv_id": arxiv_id, "priority": "high", "timestamp": time.time()})
            await self.redis.lpush("corpus:ingestion:queue", task_data)
            logger.info(f"Fallback List Queue: Pushed {arxiv_id} to queue list.")
            return True
        except Exception as e:
            logger.error(f"List queue push failed for {arxiv_id}: {e}")
            return False
