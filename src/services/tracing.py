"""Corpus — Langfuse Tracing Integration.

Enables full trace-level observability across the agentic graph,
mapping prompt templates and performance metric tracking.
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Dict, List, Optional

from src.config import get_settings

logger = logging.getLogger(__name__)

_langfuse_client = None


def get_langfuse():
    """Initialize or get the Langfuse client if enabled."""
    global _langfuse_client
    settings = get_settings()

    if not settings.langfuse.enabled:
        return None

    if _langfuse_client is None:
        try:
            from langfuse import Langfuse

            # Check if keys are set
            if not settings.langfuse.public_key or "xxxxxxxx" in settings.langfuse.public_key:
                logger.warning("Langfuse public key is not configured. Tracing is inactive.")
                return None

            _langfuse_client = Langfuse(
                public_key=settings.langfuse.public_key,
                secret_key=settings.langfuse.secret_key,
                host=settings.langfuse.host,
            )
            logger.info("Langfuse client initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Langfuse client: {e}")
            _langfuse_client = None

    return _langfuse_client


def trace_node(node_name: str):
    """Decorator to trace LangGraph nodes using Langfuse.

    Creates spans and logs inputs/outputs.
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(state: Dict[str, Any], *args, **kwargs):
            lf = get_langfuse()
            if not lf:
                return await func(state, *args, **kwargs)

            trace_id = state.get("session_id", "default_session")
            query = state.get("query", "")

            try:
                from langfuse import propagate_attributes

                with propagate_attributes(
                    session_id=trace_id,
                    metadata={"query_type": state.get("query_type", "unknown")},
                    trace_name="agentic_rag_flow",
                ):
                    with lf.start_as_current_observation(
                        as_type="span",
                        name=node_name,
                        input={"query": state.get("current_query", query), "retry_count": state.get("retry_count", 0)},
                    ) as span:
                        # Execute original node function
                        result = await func(state, *args, **kwargs)

                        # Log success output
                        span.update(
                            output={
                                "has_relevant": len(result.get("relevant_chunks", [])) > 0
                                if "relevant_chunks" in result else None,
                                "query_type": result.get("query_type"),
                            }
                        )
                        return result

            except Exception as e:
                logger.error(f"Error in traced node '{node_name}': {e}")
                raise e

        return wrapper
    return decorator


def register_prompt(name: str, template: str) -> None:
    """Register prompt templates with Langfuse for versioning."""
    lf = get_langfuse()
    if not lf:
        return
    try:
        # Langfuse supports client-side prompt registration/getting
        # But we will use the standard logging or fallback safely.
        lf.create_prompt(
            name=name,
            prompt=template,
            is_active=True
        )
    except Exception as e:
        logger.debug(f"Langfuse prompt registration skipped/failed for '{name}': {e}")
