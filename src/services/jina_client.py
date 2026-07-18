from __future__ import annotations

import logging

import httpx

from src.config import get_settings

logger = logging.getLogger(__name__)


class JinaEmbeddingsClient:
    """API client for generating embeddings via Jina AI."""

    def __init__(self):
        self.settings = get_settings()
        self.base_url = "https://api.jina.ai/v1"
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Instantiate or retrieve async http client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=60.0,
                headers={
                    "Authorization": f"Bearer {self.settings.jina.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def embed_passages(self, texts: list[str]) -> list[list[float]]:
        """Generate high-dimension embeddings using the Jina retrieval task adapter.

        If Jina API key is missing, defaults to structured dummy vector representations to enable testing.
        """
        api_key = self.settings.jina.api_key
        # Check if dummy value is configured
        if not api_key or "your_jina_api_key" in api_key:
            logger.warning("Jina API key not configured. Emitting dummy mock embeddings for local test.")
            dummy_dim = self.settings.opensearch.vector_dimension
            # Emit a mock 1024-dimensional normalized vector
            return [[1.0] + [0.0] * (dummy_dim - 1) for _ in texts]

        client = await self._get_client()
        url = f"{self.base_url}/embeddings"

        payload = {
            "model": self.settings.jina.embedding_model,
            "task": "retrieval.passage",
            "dimensions": self.settings.opensearch.vector_dimension,
            "input": texts,
        }

        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            response_data = resp.json()
            # Extract list of embeddings
            embeddings = [item["embedding"] for item in response_data["data"]]
            return embeddings
        except Exception as e:
            logger.error(f"Failed Jina Embeddings API call: {e}")
            raise RuntimeError("Embeddings generation failed.") from e

    async def embed_query(self, query: str) -> list[float]:
        """Generate a single query embedding using the Jina query task adapter.

        Uses 'retrieval.query' task for asymmetric embedding (query vs passages).
        """
        api_key = self.settings.jina.api_key
        if not api_key or "your_jina_api_key" in api_key:
            logger.warning("Jina API key not configured. Emitting dummy mock embedding for query.")
            dummy_dim = self.settings.opensearch.vector_dimension
            return [1.0] + [0.0] * (dummy_dim - 1)

        client = await self._get_client()
        url = f"{self.base_url}/embeddings"

        payload = {
            "model": self.settings.jina.embedding_model,
            "task": "retrieval.query",
            "dimensions": self.settings.opensearch.vector_dimension,
            "input": [query],
        }

        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            response_data = resp.json()
            return response_data["data"][0]["embedding"]
        except Exception as e:
            logger.error(f"Failed Jina Query Embeddings API call: {e}")
            raise RuntimeError("Query embedding generation failed.") from e

    async def close(self) -> None:
        """Teardown HTTP clients."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
