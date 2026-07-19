"""Corpus — startup model auto-selection.

Free-RAM probing is structurally wrong inside the Docker VM (it sees the 7GB
WSL slice, not the host), so we probe by trying: adopt whatever Ollama already
has loaded, else walk a preference ladder and keep the first model that
actually answers a 1-token generation within the timeout.
"""

from __future__ import annotations

import logging

import httpx

from src.config import get_settings

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_S = 45.0


async def autoselect_models() -> None:
    """Pick the largest workable LLM at startup; mutate the settings singleton once."""
    settings = get_settings()
    if not settings.model_autoselect:
        return

    ladder = [m.strip() for m in settings.model_ladder.split(",") if m.strip()]
    if not ladder:
        return

    async with httpx.AsyncClient(base_url=settings.ollama.host, timeout=PROBE_TIMEOUT_S) as client:
        # 1. Adopt an already-loaded model (zero risk, zero latency)
        try:
            ps = (await client.get("/api/ps")).json().get("models", [])
            loaded = [m["name"] for m in ps if m.get("name")]
            for candidate in ladder:
                if candidate in loaded:
                    _apply(candidate, loaded_fast(loaded, ladder))
                    logger.info(f"Model autoselect: adopted already-loaded {candidate}")
                    return
        except Exception as e:
            logger.warning(f"Model autoselect: /api/ps probe failed ({e})")

        # 2. Installed models ∩ ladder, try-load top-down
        try:
            tags = (await client.get("/api/tags")).json().get("models", [])
            installed = {m["name"] for m in tags if m.get("name")}
        except Exception as e:
            logger.warning(f"Model autoselect: /api/tags failed ({e}); keeping configured models")
            return

        for candidate in [m for m in ladder if m in installed]:
            try:
                resp = await client.post(
                    "/api/generate",
                    json={
                        "model": candidate,
                        "prompt": "ping",
                        "options": {"num_predict": 1},
                        "keep_alive": "30m",
                        "stream": False,
                    },
                )
                resp.raise_for_status()
                _apply(candidate, smallest(installed, ladder))
                logger.info(f"Model autoselect: selected {candidate}")
                return
            except Exception as e:
                logger.warning(f"Model autoselect: {candidate} failed to load ({e}); trying next")

    logger.warning("Model autoselect: no ladder model loaded; keeping configured models")


def loaded_fast(loaded: list[str], ladder: list[str]) -> str | None:
    """Prefer an already-loaded small model for the fast role."""
    for m in reversed(ladder):
        if m in loaded:
            return m
    return None


def smallest(installed: set[str], ladder: list[str]) -> str | None:
    """Ladder is ordered largest→smallest; the last installed entry is the fast pick."""
    for m in reversed(ladder):
        if m in installed:
            return m
    return None


def _apply(main_model: str, fast_model: str | None) -> None:
    settings = get_settings()
    settings.litellm.default_model = f"ollama/{main_model}"
    settings.litellm.reasoning_model = f"ollama/{main_model}"
    settings.litellm.drafting_model = f"ollama/{main_model}"
    if fast_model:
        settings.litellm.fast_model = f"ollama/{fast_model}"
