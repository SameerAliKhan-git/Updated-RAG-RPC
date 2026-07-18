"""Embedding client — pluggable backend, local sentence-transformers by default.

The local backend runs BAAI/bge-m3 (1024-dim, matches the OpenSearch knn_vector
mapping) fully offline. There is deliberately no dummy-vector fallback: if the
model cannot load, we fail loudly rather than silently break retrieval.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from abc import ABC, abstractmethod

from src.config import get_settings

logger = logging.getLogger(__name__)

_model_lock = threading.Lock()
_model = None


def _get_model():
    """Load the SentenceTransformer once per process (~2 GB RAM, ~10s)."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer

                settings = get_settings()
                logger.info(
                    "Loading embedding model %s on %s ...",
                    settings.embedding.model_name,
                    settings.embedding.device,
                )
                _model = SentenceTransformer(
                    settings.embedding.model_name,
                    device=settings.embedding.device,
                )
                logger.info("Embedding model loaded.")
    return _model


class EmbeddingClientInterface(ABC):
    """Contract shared by all embedding backends."""

    @abstractmethod
    async def embed_passages(self, texts: list[str]) -> list[list[float]]:
        """Embed document passages for indexing."""

    @abstractmethod
    async def embed_query(self, query: str) -> list[float]:
        """Embed a search query."""

    async def close(self) -> None:  # noqa: B027
        """Teardown hook; local backend holds no network resources."""


class LocalEmbeddingClient(EmbeddingClientInterface):
    """bge-m3 via sentence-transformers. encode() is not re-entrant on CPU,
    so calls are serialized with an asyncio lock and run in a worker thread."""

    def __init__(self):
        self.settings = get_settings()
        self._lock = asyncio.Lock()

    def _encode(self, texts: list[str]) -> list[list[float]]:
        model = _get_model()
        embeddings = model.encode(
            texts,
            batch_size=self.settings.embedding.batch_size,
            normalize_embeddings=self.settings.embedding.normalize,
            show_progress_bar=False,
        )
        return [vec.tolist() for vec in embeddings]

    async def embed_passages(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        async with self._lock:
            return await asyncio.to_thread(self._encode, texts)

    async def embed_query(self, query: str) -> list[float]:
        async with self._lock:
            result = await asyncio.to_thread(self._encode, [query])
        return result[0]


def warm_embedding_model() -> None:
    """Eagerly load the model (call from app lifespan to avoid first-request latency)."""
    if get_settings().embedding.backend == "local":
        _get_model()


def create_embedding_client() -> EmbeddingClientInterface:
    """Factory on EMBEDDING__BACKEND. 'jina' kept only as a rollback path."""
    settings = get_settings()
    if settings.embedding.backend == "jina":
        from src.services.jina_client import JinaEmbeddingsClient

        logger.warning("Using legacy Jina embedding backend (paid API).")
        return JinaEmbeddingsClient()  # type: ignore[return-value]
    return LocalEmbeddingClient()
