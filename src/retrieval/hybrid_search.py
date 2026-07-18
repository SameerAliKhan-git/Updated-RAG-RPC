"""Corpus — Hybrid Retrieval Service.

Combines BM25 full-text search and KNN vector similarity search
using OpenSearch's Reciprocal Rank Fusion (RRF) pipeline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from opensearchpy import OpenSearch

from src.config import get_settings
from src.services.embedding_client import create_embedding_client

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    """A single retrieved chunk with relevance metadata."""

    chunk_id: str
    arxiv_id: str
    paper_id: str
    section_title: str
    chunk_type: str
    text: str
    title: str
    authors: list[str]
    abstract: str
    categories: list[str]
    published_date: str
    score: float = 0.0

    @property
    def paper_title(self) -> str:
        """Alias for consistency with the context builder."""
        return self.title

    @property
    def citation(self) -> str:
        """Build a human-readable citation string."""
        author_str = ", ".join(self.authors[:3])
        if len(self.authors) > 3:
            author_str += " et al."
        return f'[{self.arxiv_id}] {author_str}. "{self.title}". Section: {self.section_title}'


class HybridSearchService:
    """Execute hybrid (BM25 + KNN) searches against the corpus-chunks index."""

    def __init__(self, opensearch_client: OpenSearch):
        self.client = opensearch_client
        self.settings = get_settings()
        self.embeddings_client = create_embedding_client()
        self.index_name = self.settings.opensearch.chunk_index_name

    async def search(
        self,
        query: str,
        top_k: int = 10,
        filter_arxiv_id: str | None = None,
        filter_chunk_type: str | None = None,
        filter_categories: list[str] | None = None,
        filter_authors: list[str] | None = None,
        filter_date_from: str | None = None,
        filter_date_to: str | None = None,
    ) -> list[RetrievedChunk]:
        """Run hybrid BM25 + KNN search with RRF fusion.

        Args:
            query: Natural-language user query.
            top_k: Number of top results to return.
            filter_arxiv_id: Optional arXiv ID to narrow search to a single paper.
            filter_chunk_type: Optional chunk type filter (body, table, equation).

        Returns:
            List of RetrievedChunk ordered by relevance.
        """
        # 1. Embed the query
        query_embedding = await self._embed_query(query)

        # 2. Build filter clauses
        filter_clauses = self._build_filters(
            filter_arxiv_id,
            filter_chunk_type,
            filter_categories,
            filter_authors,
            filter_date_from,
            filter_date_to,
        )

        # 3. Construct hybrid query
        hybrid_body = self._build_hybrid_query(query, query_embedding, top_k, filter_clauses)

        # 4. Execute search
        try:
            response = self.client.search(
                index=self.index_name,
                body=hybrid_body,
                params={"search_pipeline": self.settings.opensearch.rrf_pipeline_name},
            )
        except Exception as e:
            logger.error(f"OpenSearch hybrid search failed: {e}")
            # Fallback to BM25-only
            return await self._fallback_bm25_search(query, top_k, filter_clauses)

        # 5. Parse results
        return self._parse_results(response)

    async def _embed_query(self, query: str) -> list[float]:
        """Generate query embedding using Jina."""
        api_key = self.settings.jina.api_key
        if not api_key or "your_jina_api_key" in api_key:
            # Use dummy embedding for development
            dim = self.settings.opensearch.vector_dimension
            return [1.0] + [0.0] * (dim - 1)

        embeddings = await self.embeddings_client.embed_query(query)
        return embeddings

    async def _fallback_bm25_search(self, query: str, top_k: int, filter_clauses: list[dict]) -> list[RetrievedChunk]:
        """Pure BM25 fallback if hybrid search fails."""
        must_clauses: list[dict] = [
            {
                "multi_match": {
                    "query": query,
                    "fields": ["text^3", "title^2", "abstract", "section_title"],
                    "type": "best_fields",
                }
            }
        ]

        body = {
            "size": top_k,
            "query": {
                "bool": {
                    "must": must_clauses,
                    "filter": filter_clauses,
                }
            },
            "_source": {"excludes": ["embedding"]},
        }

        try:
            response = self.client.search(index=self.index_name, body=body)
            return self._parse_results(response)
        except Exception as e:
            logger.error(f"BM25 fallback search also failed: {e}")
            return []

    def _build_filters(
        self,
        filter_arxiv_id: str | None = None,
        filter_chunk_type: str | None = None,
        filter_categories: list[str] | None = None,
        filter_authors: list[str] | None = None,
        filter_date_from: str | None = None,
        filter_date_to: str | None = None,
    ) -> list[dict]:
        """Build OpenSearch filter clauses for metadata-based filtering."""
        filters = []
        if filter_arxiv_id:
            filters.append({"term": {"arxiv_id": filter_arxiv_id}})
        if filter_chunk_type:
            filters.append({"term": {"chunk_type": filter_chunk_type}})
        if filter_categories:
            filters.append({"terms": {"categories": filter_categories}})
        if filter_authors:
            # Match any of the specified authors
            filters.append({"terms": {"authors": filter_authors}})
        if filter_date_from or filter_date_to:
            date_range: dict[str, str] = {}
            if filter_date_from:
                date_range["gte"] = filter_date_from
            if filter_date_to:
                date_range["lte"] = filter_date_to
            filters.append({"range": {"published_date": date_range}})
        return filters

    def _build_hybrid_query(
        self,
        query: str,
        query_embedding: list[float],
        top_k: int,
        filter_clauses: list[dict],
    ) -> dict[str, Any]:
        """Construct the OpenSearch hybrid query body for RRF pipeline."""
        bm25_query: dict[str, Any] = {
            "multi_match": {
                "query": query,
                "fields": ["text^3", "title^2", "abstract", "section_title"],
                "type": "best_fields",
            }
        }

        knn_query: dict[str, Any] = {
            "embedding": {
                "vector": query_embedding,
                "k": top_k,
            }
        }

        body: dict[str, Any] = {
            "size": top_k,
            "_source": {"excludes": ["embedding"]},
            "query": {
                "hybrid": {
                    "queries": [
                        # Sub-query 1: BM25 text relevance
                        {
                            "bool": {
                                "must": [bm25_query],
                                "filter": filter_clauses,
                            }
                        },
                        # Sub-query 2: KNN vector similarity
                        {"knn": knn_query},
                    ]
                }
            },
        }

        return body

    def _parse_results(self, response: dict) -> list[RetrievedChunk]:
        """Parse OpenSearch response into RetrievedChunk objects."""
        chunks = []
        hits = response.get("hits", {}).get("hits", [])
        for hit in hits:
            source = hit.get("_source", {})
            chunks.append(
                RetrievedChunk(
                    chunk_id=source.get("chunk_id", ""),
                    arxiv_id=source.get("arxiv_id", ""),
                    paper_id=source.get("paper_id", ""),
                    section_title=source.get("section_title", ""),
                    chunk_type=source.get("chunk_type", ""),
                    text=source.get("text", ""),
                    title=source.get("title", ""),
                    authors=source.get("authors", []),
                    abstract=source.get("abstract", ""),
                    categories=source.get("categories", []),
                    published_date=source.get("published_date", ""),
                    score=hit.get("_score", 0.0),
                )
            )
        return chunks

    async def close(self) -> None:
        """Clean up resources."""
        await self.embeddings_client.close()
