"""Corpus — Thin LLM Adapter via LiteLLM.

Wraps LiteLLM's acompletion() to provide a pluggable, model-routable interface.
Different graph nodes can use different models — reasoning-heavy nodes
(planning, grading, verification) get the strongest model, bulk drafting
gets the cheapest one. Swapping Ollama → vLLM → SGLang is a config change.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from src.config import get_settings

logger = logging.getLogger(__name__)


async def _call_litellm(
    model: str,
    messages: List[Dict[str, str]],
    temperature: float = 0.1,
    max_tokens: int = 2048,
    response_format: Optional[Dict[str, Any]] = None,
    stream: bool = False,
) -> str:
    """Core LiteLLM call — handles import and fallback gracefully."""
    settings = get_settings()

    try:
        import litellm

        litellm.set_verbose = False

        # Set Ollama base URL if using Ollama models
        if model.startswith("ollama/"):
            litellm.api_base = settings.ollama.host

        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": settings.litellm.timeout,
            "num_retries": settings.litellm.max_retries,
        }

        if response_format:
            kwargs["response_format"] = response_format

        response = await litellm.acompletion(**kwargs)
        return response.choices[0].message.content or ""

    except ImportError:
        logger.warning("litellm not installed — falling back to langchain-ollama.")
        return await _ollama_fallback(model, messages, temperature, max_tokens)
    except Exception as e:
        logger.error(f"LiteLLM call failed for model '{model}': {e}")
        return await _ollama_fallback(model, messages, temperature, max_tokens)


async def _ollama_fallback(
    model: str,
    messages: List[Dict[str, str]],
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
        return response.content if hasattr(response, "content") else str(response)

    except Exception as e:
        logger.error(f"Ollama fallback also failed: {e}")
        return f"[LLM Error: {e}]"


async def call_reasoning_llm(
    messages: List[Dict[str, str]],
    temperature: float = 0.1,
    max_tokens: int = 2048,
    response_format: Optional[Dict[str, Any]] = None,
) -> str:
    """Call the reasoning model — used for planning, grading, verification.

    These are high-stakes, low-volume calls that need the strongest model.
    """
    settings = get_settings()
    model = settings.litellm.reasoning_model
    logger.debug(f"Reasoning LLM call: model={model}")
    return await _call_litellm(model, messages, temperature, max_tokens, response_format)


async def call_drafting_llm(
    messages: List[Dict[str, str]],
    temperature: float = 0.3,
    max_tokens: int = 4096,
    response_format: Optional[Dict[str, Any]] = None,
) -> str:
    """Call the drafting model — used for answer generation.

    Higher volume, can use a cheaper/faster model.
    """
    settings = get_settings()
    model = settings.litellm.drafting_model
    logger.debug(f"Drafting LLM call: model={model}")
    return await _call_litellm(model, messages, temperature, max_tokens, response_format)


def parse_json_response(response: str) -> Dict[str, Any]:
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
