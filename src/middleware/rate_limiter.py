"""Corpus — Redis-based Sliding Window Rate Limiter.

Implements a sliding window counter per API key (or IP).
Returns 429 Too Many Requests with Retry-After header when exceeded.
"""

from __future__ import annotations

import logging
import time

from fastapi import HTTPException, Request

from src.config import get_settings

logger = logging.getLogger(__name__)

# Default: 30 requests per minute
DEFAULT_REQUESTS_PER_MINUTE = 30
DEFAULT_WINDOW_SECONDS = 60


class RateLimiter:
    """Redis-backed sliding window rate limiter.

    Usage as a FastAPI dependency:
        @router.post("/ask-agentic", dependencies=[Depends(rate_limiter)])
    """

    def __init__(
        self,
        requests_per_minute: int = DEFAULT_REQUESTS_PER_MINUTE,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
    ):
        self.max_requests = requests_per_minute
        self.window = window_seconds

    async def __call__(self, request: Request) -> None:
        """Check rate limit for the current request."""
        settings = get_settings()

        # Skip rate limiting in dev mode
        if settings.debug and settings.environment == "development":
            return

        # Get Redis client from app state
        redis = getattr(request.app.state, "redis", None)
        if redis is None:
            logger.warning("Redis not available — rate limiting disabled.")
            return

        # Identify the client by API key or IP
        api_key = request.headers.get("X-API-Key", "")
        client_id = api_key or request.client.host if request.client else "unknown"
        key = f"corpus:ratelimit:{client_id}"

        try:
            now = time.time()
            window_start = now - self.window

            pipe = redis.pipeline()
            # Remove expired entries
            pipe.zremrangebyscore(key, 0, window_start)
            # Add current request
            pipe.zadd(key, {str(now): now})
            # Count requests in window
            pipe.zcard(key)
            # Set TTL on the key
            pipe.expire(key, self.window + 10)

            results = await pipe.execute()
            request_count = results[2]

            if request_count > self.max_requests:
                retry_after = int(self.window - (now - window_start))
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Maximum {self.max_requests} requests per {self.window}s.",
                    headers={"Retry-After": str(max(1, retry_after))},
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Rate limiter error: {e} — allowing request.")


# Pre-built instance for standard API routes
rate_limiter = RateLimiter(requests_per_minute=30)
