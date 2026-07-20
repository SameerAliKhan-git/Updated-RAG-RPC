"""Corpus — Thin LLM Adapter via LiteLLM.

Wraps LiteLLM's acompletion() to provide a pluggable, model-routable interface.
Different graph nodes can use different models — reasoning-heavy nodes
(planning, grading, verification) get the strongest model, bulk drafting
gets the cheapest one. Swapping Ollama → vLLM → SGLang is a config change.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncGenerator
from typing import Any

from src.config import get_settings
from src.services.resilience import llm_circuit_breaker

logger = logging.getLogger(__name__)


@llm_circuit_breaker
async def _protected_acompletion(**kwargs: Any):
    """LiteLLM completion behind the shared LLM circuit breaker.

    When the breaker is open, calls fail fast instead of hammering a
    downed Ollama; the fallback path shares the same breaker state.
    """
    import litellm

    return await litellm.acompletion(**kwargs)


_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def _strip_think(text: str) -> str:
    """Remove qwen3-style <think>...</think> reasoning blocks from output."""
    return _THINK_BLOCK_RE.sub("", text).strip()


def _prepare_messages(model: str, messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Disable qwen3 thinking mode for structured calls — reasoning blocks break JSON parsing."""
    if "qwen3" not in model:
        return messages
    prepared = [dict(m) for m in messages]
    for msg in prepared:
        if msg.get("role") == "system":
            msg["content"] = f"{msg['content']}\n/no_think"
            return prepared
    prepared.insert(0, {"role": "system", "content": "/no_think"})
    return prepared


def _record_llm_metrics(role: str, response: Any) -> None:
    """Count completions and tokens per role; never let metrics break a call."""
    try:
        from src.middleware.metrics import LLM_CALLS, LLM_TOKENS

        LLM_CALLS.labels(role=role).inc()
        usage = getattr(response, "usage", None)
        completion_tokens = getattr(usage, "completion_tokens", None) if usage else None
        if completion_tokens:
            LLM_TOKENS.labels(role=role).inc(completion_tokens)
    except Exception:  # noqa: BLE001
        pass


async def _call_litellm(
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0.1,
    max_tokens: int = 2048,
    response_format: dict[str, Any] | None = None,
    stream: bool = False,
    role: str = "default",
) -> str:
    """Core LiteLLM call — handles import and fallback gracefully."""
    settings = get_settings()

    try:
        import litellm

        litellm.set_verbose = False

        # Set Ollama base URL if using Ollama models
        if model.startswith("ollama/"):
            litellm.api_base = settings.ollama.host

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": _prepare_messages(model, messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": settings.litellm.timeout,
            "num_retries": settings.litellm.max_retries,
        }

        if response_format:
            kwargs["response_format"] = response_format

        response = await _protected_acompletion(**kwargs)
        _record_llm_metrics(role, response)
        return _strip_think(response.choices[0].message.content or "")

    except ImportError:
        logger.warning("litellm not installed — falling back to langchain-ollama.")
        return await _ollama_fallback(model, messages, temperature, max_tokens)
    except Exception as e:
        logger.error(f"LiteLLM call failed for model '{model}': {e}")
        return await _ollama_fallback(model, messages, temperature, max_tokens)


async def _ollama_fallback(
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
) -> str:
    """Fallback to direct ChatOllama if LiteLLM is unavailable."""
    try:
        from langchain_ollama import ChatOllama

        settings = get_settings()
        # Strip 'ollama/' prefix if present
        model_name = model.replace("ollama/", "")
        llm = ChatOllama(
            model=model_name,
            base_url=settings.ollama.host,
            temperature=temperature,
            num_predict=max_tokens,
        )
        from langchain_core.messages import HumanMessage, SystemMessage

        lc_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                lc_messages.append(SystemMessage(content=content))
            else:
                lc_messages.append(HumanMessage(content=content))

        response = await llm.ainvoke(lc_messages)
        content = response.content if hasattr(response, "content") else response
        return _strip_think(content if isinstance(content, str) else str(content))

    except Exception as e:
        logger.error(f"Ollama fallback also failed: {e}")
        return f"[LLM Error: {e}]"


async def call_reasoning_llm(
    messages: list[dict[str, str]],
    temperature: float = 0.1,
    max_tokens: int = 2048,
    response_format: dict[str, Any] | None = None,
) -> str:
    """Call the reasoning model — used for planning, grading, verification.

    These are high-stakes, low-volume calls that need the strongest model.
    """
    settings = get_settings()
    model = settings.litellm.reasoning_model
    logger.debug(f"Reasoning LLM call: model={model}")
    return await _call_litellm(model, messages, temperature, max_tokens, response_format, role="reasoning")


async def call_drafting_llm(
    messages: list[dict[str, str]],
    temperature: float = 0.3,
    max_tokens: int = 4096,
    response_format: dict[str, Any] | None = None,
) -> str:
    """Call the drafting model — used for answer generation.

    Higher volume, can use a cheaper/faster model.
    """
    settings = get_settings()
    model = settings.litellm.drafting_model
    logger.debug(f"Drafting LLM call: model={model}")
    return await _call_litellm(model, messages, temperature, max_tokens, response_format, role="drafting")


async def call_fast_llm(
    messages: list[dict[str, str]],
    temperature: float = 0.1,
    max_tokens: int = 1024,
    response_format: dict[str, Any] | None = None,
) -> str:
    """Call the fast model — used for routing, grading, and query rewriting.

    Latency-critical, high-frequency calls where a small model is sufficient.
    """
    settings = get_settings()
    model = settings.litellm.fast_model
    logger.debug(f"Fast LLM call: model={model}")
    return await _call_litellm(model, messages, temperature, max_tokens, response_format, role="fast")


async def stream_drafting_llm(
    messages: list[dict[str, str]],
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> AsyncGenerator[str, None]:
    """Stream tokens from the drafting model as they are generated.

    Buffers a leading <think>...</think> block (qwen3) so reasoning
    never leaks into the user-visible stream.
    """
    settings = get_settings()
    model = settings.litellm.drafting_model

    import litellm

    if model.startswith("ollama/"):
        litellm.api_base = settings.ollama.host

    response = await _protected_acompletion(
        model=model,
        messages=_prepare_messages(model, messages),
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=settings.litellm.timeout,
        stream=True,
    )

    buffering = True  # buffer until we know the stream doesn't open with <think>
    buffer = ""
    async for chunk in response:
        delta = chunk.choices[0].delta.content or ""
        if not delta:
            continue
        if buffering:
            buffer += delta
            stripped = buffer.lstrip()
            if stripped.startswith("<think>") or "<think>".startswith(stripped[:7]):
                if "</think>" in buffer:
                    remainder = _strip_think(buffer)
                    buffer = ""
                    buffering = False
                    if remainder:
                        yield remainder
                # else: still inside the think block — keep buffering
            else:
                buffering = False
                out, buffer = buffer, ""
                yield out
        else:
            yield delta
    if buffer:
        remainder = _strip_think(buffer)
        if remainder:
            yield remainder


def parse_json_response(response: str) -> dict[str, Any]:
    """Parse a JSON response from the LLM, handling markdown code blocks."""
    text = response.strip()
    # Strip markdown code fences
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON in the response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        logger.warning(f"Failed to parse JSON from LLM response: {text[:200]}")
        return {}
