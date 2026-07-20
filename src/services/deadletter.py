"""Corpus — background-job dead-letter record.

The arq worker catches its own exceptions and returns a failure dict, so
arq's built-in failure tracking never fires and a failed ingestion vanishes
into logs. This records failures to a capped Redis list so an operator can
see "what background jobs failed and why" and re-trigger them.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

DEADLETTER_KEY = "corpus:deadletter"
DEADLETTER_MAX = 50


async def record_failed_job(redis, job_name: str, target: str, error: str) -> None:
    """Append a failed job to the capped dead-letter list. Never raises —
    dead-lettering must not mask the original failure."""
    try:
        entry = json.dumps({"job": job_name, "target": target, "error": error[:500], "ts": time.time()})
        await redis.lpush(DEADLETTER_KEY, entry)
        await redis.ltrim(DEADLETTER_KEY, 0, DEADLETTER_MAX - 1)
    except Exception as e:  # noqa: BLE001 — never let bookkeeping break the caller
        logger.warning(f"Could not record dead-letter entry for {target}: {e}")


async def list_failed_jobs(redis, limit: int = DEADLETTER_MAX) -> list[dict[str, Any]]:
    """Return recent failed jobs, newest first."""
    try:
        raw = await redis.lrange(DEADLETTER_KEY, 0, limit - 1)
        return [json.loads(r) for r in raw]
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Could not read dead-letter list: {e}")
        return []


async def clear_failed_jobs(redis) -> None:
    try:
        await redis.delete(DEADLETTER_KEY)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Could not clear dead-letter list: {e}")
