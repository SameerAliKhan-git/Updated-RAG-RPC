"""Corpus — Pluggable Reranker Interface and Implementations.

Provides cross-encoder reranking of hybrid search results — promoted to
a core, non-optional stage in the retrieval pipeline. The spec is explicit:
skipping a reranker after RRF fusion is the single most common cause of
"retrieval found it but the answer still missed it."
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import List

import httpx

from src.config import get_settings
from src.retrieval.hybrid_search import RetrievedChunk

logger = logging.getLogger(__name__)


class RerankerInterface(ABC):
    """Abstract reranker — implementations must score and re-order chunks."""

    @abstractmethod
    async def rerank(
        self, query: str, chunks: List[RetrievedChunk], top_k: int = 8
    ) -> List[RetrievedChunk]:
        """Rerank chunks by relevance to query. Return top_k ordered by score."""
        pass

    async def close(self) -> None:
        """Clean up resources."""
        pass


class JinaReranker(RerankerInterface):
    """Cross-encoder reranker via the Jina Reranker API."""

    def __init__(self):
        self.settings = get_settings()
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=float(self.settings.reranker.timeout),
                headers={
                    "Authorization": f"Bearer {self.settings.jina.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def rerank(
        self, query: str, chunks: List[RetrievedChunk], top_k: int = 8
    ) -> List[RetrievedChunk]:
        """Rerank using Jina cross-encoder reranker API."""
        if not chunks:
            return []

        client = await self._get_client()

        documents = [c.text[:2000] for c in chunks]  # Truncate for API limits

        payload = {
            "model": self.settings.reranker.model,
            "query": query,
            "documents": documents,
            "top_n": min(top_k, len(chunks)),
        }

        try:
            resp = await client.post("https://api.jina.ai/v1/rerank", json=payload)
            resp.raise_for_status()
            data = resp.json()

            # Map results back to chunks by index, ordered by relevance_score
            results = data.get("results", [])
            reranked = []
            for result in results:
                idx = result["index"]
                chunk = chunks[idx]
                chunk.score = result["relevance_score"]
                reranked.append(chunk)

            logger.info(
                f"Jina reranker: {len(chunks)} candidates → {len(reranked)} reranked"
            )
            return reranked

        except Exception as e:
            logger.error(f"Jina reranker failed: {e}. Falling back to original order.")
            return chunks[:top_k]

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


class NoOpReranker(RerankerInterface):
    """Pass-through reranker for dev/testing — returns chunks in original score order."""

    async def rerank(
        self, query: str, chunks: List[RetrievedChunk], top_k: int = 8
    ) -> List[RetrievedChunk]:
        logger.warning("NoOpReranker active — using original hybrid search scores.")
        sorted_chunks = sorted(chunks, key=lambda c: c.score, reverse=True)
        return sorted_chunks[:top_k]


def create_reranker() -> RerankerInterface:
    """Factory — create a reranker based on config and available API keys."""
    settings = get_settings()

    if not settings.reranker.enabled:
        logger.info("Reranker disabled via config.")
        return NoOpReranker()

    api_key = settings.jina.api_key
    if not api_key or "your_jina_api_key" in api_key:
        logger.warning(
            "Jina API key not configured — reranker disabled. "
            "Set JINA_API_KEY for production-quality retrieval."
        )
        return NoOpReranker()

    backend = settings.reranker.backend.lower()
    if backend == "jina":
        logger.info("Using Jina Reranker backend.")
        return JinaReranker()
    elif backend == "noop":
        return NoOpReranker()
    else:
        logger.warning(f"Unknown reranker backend '{backend}', falling back to NoOp.")
        return NoOpReranker()
