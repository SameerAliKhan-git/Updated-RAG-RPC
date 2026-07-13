"""Corpus — Resilience Patterns (Retries and Circuit Breakers).

Provides decorators for handling transient errors in external APIs
(arXiv API, Embeddings, Reranker, LLM calls) safely.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from typing import Any, Callable, Dict, Type

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


# ─── Retries with Exponential Backoff ──────────────────────────────


def with_retry(
    max_attempts: int = 3,
    min_seconds: float = 1.0,
    max_seconds: float = 10.0,
    exceptions: tuple[Type[BaseException], ...] = (Exception,),
):
    """Decorator to retry a function with exponential backoff on specified exceptions."""
    def decorator(func):
        @retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=min_seconds, max=max_seconds),
            retry=retry_if_exception_type(exceptions),
            reraise=True,
            before_sleep=lambda retry_state: logger.warning(
                f"Retrying {func.__name__} due to {retry_state.outcome.exception()}. "
                f"Attempt {retry_state.attempt_number} of {max_attempts}."
            ),
        )
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            return func(*args, **kwargs)
        return wrapper
    return decorator


# ─── Circuit Breaker ───────────────────────────────────────────────


class CircuitBreakerOpenException(Exception):
    """Exception raised when the circuit breaker is open."""
    pass


class CircuitBreaker:
    """Stateful circuit breaker pattern to prevent cascading failures."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        name: str = "default",
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.name = name

        self.state = "CLOSED"  # CLOSED, OPEN, HALF-OPEN
        self.failures = 0
        self.last_state_change = time.time()

    def __call__(self, func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            now = time.time()

            # Check state transitions
            if self.state == "OPEN":
                if now - self.last_state_change > self.recovery_timeout:
                    self.state = "HALF-OPEN"
                    self.last_state_change = now
                    logger.info(f"Circuit Breaker '{self.name}' entering HALF-OPEN state.")
                else:
                    raise CircuitBreakerOpenException(
                        f"Circuit Breaker '{self.name}' is OPEN. Call blocked to protect downstream services."
                    )

            try:
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)

                # Successful execution
                if self.state == "HALF-OPEN":
                    self.state = "CLOSED"
                    self.failures = 0
                    self.last_state_change = now
                    logger.info(f"Circuit Breaker '{self.name}' recovered and is now CLOSED.")
                return result

            except Exception as e:
                # Execution failed
                if self.state in ("CLOSED", "HALF-OPEN"):
                    self.failures += 1
                    logger.warning(
                        f"Circuit Breaker '{self.name}' recorded failure ({self.failures}/{self.failure_threshold}): {e}"
                    )
                    if self.failures >= self.failure_threshold or self.state == "HALF-OPEN":
                        self.state = "OPEN"
                        self.last_state_change = now
                        logger.error(
                            f"Circuit Breaker '{self.name}' tripped to OPEN state for {self.recovery_timeout}s."
                        )
                raise e

        return wrapper


# Pre-built circuit breakers for major downstream services
arxiv_circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60.0, name="arXiv API")
jina_circuit_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0, name="Jina AI API")
llm_circuit_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=15.0, name="LiteLLM/Ollama")
