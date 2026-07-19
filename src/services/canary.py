"""Corpus — hourly canary probe.

A synthetic health signal that exercises the two things /health can't see:
does retrieval actually return results, and does the LLM actually answer?
Runs inside the API process (no scheduler dependency); result is stored in
Redis and surfaced by /health and the System view.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

import httpx

from src.config import get_settings

logger = logging.getLogger(__name__)

CANARY_KEY = "corpus:canary:last"
CANARY_QUERY = "What is attention in transformers?"
INTERVAL_SECONDS = 3600


async def run_canary_once(app_state) -> dict:
    """Probe retrieval + LLM availability; store and return the verdict."""
    settings = get_settings()
    result: dict = {"timestamp": time.time(), "retrieval_ok": False, "llm_ok": False, "detail": ""}

    # 1. Retrieval: real hybrid search must return at least one chunk
    try:
        from src.retrieval.hybrid_search import HybridSearchService

        service = HybridSearchService(app_state.opensearch)
        chunks = await service.search(query=CANARY_QUERY, top_k=3)
        await service.close()
        result["retrieval_ok"] = len(chunks) > 0
        if not chunks:
            result["detail"] = "hybrid search returned 0 chunks"
    except Exception as e:
        result["detail"] = f"retrieval: {e}"

    # 2. LLM: a 1-token generation must succeed
    try:
        model = settings.litellm.fast_model.replace("ollama/", "")
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                f"{settings.ollama.host}/api/generate",
                json={"model": model, "prompt": "ping", "stream": False, "options": {"num_predict": 1}},
            )
            resp.raise_for_status()
            result["llm_ok"] = "error" not in resp.json()
            if not result["llm_ok"]:
                result["detail"] += f" | llm: {resp.json().get('error', '')[:120]}"
    except Exception as e:
        result["detail"] += f" | llm: {e}"

    result["healthy"] = result["retrieval_ok"] and result["llm_ok"]
    try:
        await app_state.redis.set(CANARY_KEY, json.dumps(result))
    except Exception as e:
        logger.warning(f"Canary: could not store result: {e}")

    level = logging.INFO if result["healthy"] else logging.ERROR
    logger.log(level, f"Canary probe: {'OK' if result['healthy'] else 'FAILING'} {result['detail']}".strip())
    return result


async def canary_loop(app_state) -> None:
    """Background loop started from the app lifespan."""
    await asyncio.sleep(120)  # let the stack settle after boot
    while True:
        try:
            await run_canary_once(app_state)
        except Exception as e:
            logger.error(f"Canary loop error: {e}")
        await asyncio.sleep(INTERVAL_SECONDS)


async def get_last_canary(redis) -> dict | None:
    try:
        raw = await redis.get(CANARY_KEY)
        return json.loads(raw) if raw else None
    except Exception:
        return None
