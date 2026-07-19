"""Corpus — Agent Tools.

The seven tools exposed to the LangGraph agentic layer, plus an ArxivLiveLookup
helper. Each tool is a thin wrapper around a service — the graph decides WHEN
to call them, the tools handle HOW.
"""

from __future__ import annotations

import logging
from typing import Any

from src.config import get_settings
from src.retrieval.hybrid_search import HybridSearchService, RetrievedChunk
from src.retrieval.reranker import RerankerInterface
from src.services.resilience import arxiv_circuit_breaker, with_retry

logger = logging.getLogger(__name__)


@arxiv_circuit_breaker
@with_retry(max_attempts=2)
async def _fetch_arxiv_feed(base_url: str, params: dict[str, Any], timeout: float) -> str:
    """Fetch an arXiv Atom feed behind the shared arXiv circuit breaker."""
    import httpx

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(base_url, params=params)
        resp.raise_for_status()
        return resp.text


class AgentToolkit:
    """Collection of tools available to the agentic graph.

    Initialized once per request with the shared service clients.
    """

    def __init__(
        self,
        search_service: HybridSearchService,
        reranker: RerankerInterface,
        db_session=None,
        redis_client=None,
    ):
        self.search = search_service
        self.reranker = reranker
        self.db_session = db_session
        self.redis = redis_client
        self.settings = get_settings()

    async def hybrid_search(
        self,
        query: str,
        top_k: int = 15,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        """Tool: hybrid_search(query, filters) — BM25 + vector + RRF."""
        filters = filters or {}
        # Accept both scalar arxiv_id (router/LLM output) and arxiv_ids list (collections)
        arxiv_ids = filters.get("arxiv_ids") or ([filters["arxiv_id"]] if filters.get("arxiv_id") else None)
        return await self.search.search(
            query=query,
            top_k=top_k,
            filter_arxiv_ids=arxiv_ids,
            filter_chunk_type=filters.get("chunk_type"),
            filter_categories=filters.get("categories"),
            filter_authors=filters.get("authors"),
            filter_date_from=filters.get("date_from"),
            filter_date_to=filters.get("date_to"),
        )

    async def rerank_chunks(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        top_k: int = 8,
    ) -> list[RetrievedChunk]:
        """Tool: rerank(candidates, query) — cross-encoder precision pass."""
        return await self.reranker.rerank(query, chunks, top_k)

    async def get_paper(self, arxiv_id: str) -> dict[str, Any] | None:
        """Tool: get_paper(arxiv_id) — fetch paper metadata from Postgres."""
        if not self.db_session:
            return None

        try:
            from src.models.paper import Paper

            paper = self.db_session.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
            if paper:
                return {
                    "arxiv_id": paper.arxiv_id,
                    "title": paper.title,
                    "authors": paper.authors if paper.authors else [],
                    "abstract": paper.abstract,
                    "published_date": str(paper.published_date) if paper.published_date else "",
                    "categories": paper.categories if paper.categories else [],
                    "pdf_url": paper.pdf_url,
                    "pdf_processed": paper.pdf_processed,
                }
        except Exception as e:
            logger.error(f"get_paper failed for {arxiv_id}: {e}")
        return None

    async def search_arxiv_live(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        """Tool: search_arxiv_live(query) — hit arXiv API directly for papers not in index."""
        settings = self.settings

        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }

        try:
            xml_content = await _fetch_arxiv_feed(settings.arxiv.base_url, params, settings.arxiv.timeout_seconds)

            # Parse Atom XML feed
            import xml.etree.ElementTree as ET

            root = ET.fromstring(xml_content)
            ns = {"atom": "http://www.w3.org/2005/Atom"}

            results = []
            for entry in root.findall("atom:entry", ns):
                title_el = entry.find("atom:title", ns)
                summary_el = entry.find("atom:summary", ns)
                arxiv_id = ""
                id_el = entry.find("atom:id", ns)
                if id_el is not None and id_el.text:
                    arxiv_id = id_el.text.split("/abs/")[-1]

                authors = []
                for author in entry.findall("atom:author", ns):
                    name_el = author.find("atom:name", ns)
                    if name_el is not None and name_el.text:
                        authors.append(name_el.text)

                results.append(
                    {
                        "arxiv_id": arxiv_id,
                        "title": title_el.text.strip() if title_el is not None and title_el.text else "",
                        "authors": authors,
                        "abstract": summary_el.text.strip() if summary_el is not None and summary_el.text else "",
                        "arxiv_url": f"https://arxiv.org/abs/{arxiv_id}",
                        "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
                    }
                )

            logger.info(f"Live arXiv search returned {len(results)} results for '{query}'")
            return results

        except Exception as e:
            logger.error(f"Live arXiv search failed: {e}")
            return []

    async def trigger_ingestion(self, arxiv_id: str) -> bool:
        """Tool: trigger_ingestion(arxiv_id) — enqueue on-demand paper ingestion via Redis/Arq."""
        if not self.redis:
            logger.warning("Redis not available — cannot queue ingestion.")
            return False

        try:
            from src.services.redis_services import RedisServicesManager

            manager = RedisServicesManager(self.redis)
            return await manager.enqueue_paper_ingestion(arxiv_id)
        except Exception as e:
            logger.error(f"Failed to queue ingestion for {arxiv_id}: {e}")
            return False

    async def list_recent(self, topic: str = "", n: int = 10) -> list[dict[str, Any]]:
        """Tool: list_recent(topic, n) — query recent papers from Postgres."""
        if not self.db_session:
            return []

        try:
            from sqlalchemy import desc

            from src.models.paper import Paper

            query = self.db_session.query(Paper).order_by(desc(Paper.published_date))

            if topic:
                query = query.filter(Paper.categories.contains([topic]))

            papers = query.limit(n).all()
            return [
                {
                    "arxiv_id": p.arxiv_id,
                    "title": p.title,
                    "authors": p.authors[:3] if p.authors else [],
                    "published_date": str(p.published_date) if p.published_date else "",
                    "categories": p.categories if p.categories else [],
                }
                for p in papers
            ]
        except Exception as e:
            logger.error(f"list_recent failed: {e}")
            return []

    async def compare(self, paper_ids: list[str], aspect: str = "") -> dict[str, list[RetrievedChunk]]:
        """Tool: compare(paper_ids, aspect) — retrieve chunks from specific papers for comparison."""
        result: dict[str, list[RetrievedChunk]] = {}
        search_query = aspect or "main contributions methods results"

        for arxiv_id in paper_ids:
            chunks = await self.search.search(
                query=search_query,
                top_k=5,
                filter_arxiv_ids=[arxiv_id],
            )
            result[arxiv_id] = chunks

        return result


class ConceptGraphTools:
    """SQL-backed concept graph lookups (built nightly by the concept_graph_builder DAG)."""

    def __init__(self, db_session):
        self.db = db_session

    def _resolve_concept(self, name: str):
        from src.models.paper import ConceptNode

        normalized = " ".join(name.lower().strip().split())
        node = self.db.query(ConceptNode).filter(ConceptNode.canonical_name == normalized).first()
        if node:
            return node
        return (
            self.db.query(ConceptNode)
            .filter(ConceptNode.canonical_name.ilike(f"{normalized}%"))
            .first()
        )

    def papers_for_concept(self, name: str, limit: int = 20) -> list[str]:
        """arxiv_ids of papers mentioning a concept — feeds scoped retrieval."""
        from src.models.paper import ConceptMention

        node = self._resolve_concept(name)
        if not node:
            return []
        rows = (
            self.db.query(ConceptMention.arxiv_id)
            .filter(ConceptMention.concept_id == node.id)
            .limit(limit)
            .all()
        )
        return [r[0] for r in rows]

    def get_concept_neighbors(self, name: str, limit: int = 25) -> list[dict[str, str]]:
        """Directly related concepts with their relation types."""
        from src.models.paper import ConceptEdge, ConceptNode

        node = self._resolve_concept(name)
        if not node:
            return []
        edges = (
            self.db.query(ConceptEdge, ConceptNode)
            .join(ConceptNode, ConceptNode.id == ConceptEdge.target_id)
            .filter(ConceptEdge.source_id == node.id)
            .limit(limit)
            .all()
        )
        reverse = (
            self.db.query(ConceptEdge, ConceptNode)
            .join(ConceptNode, ConceptNode.id == ConceptEdge.source_id)
            .filter(ConceptEdge.target_id == node.id)
            .limit(limit)
            .all()
        )
        result = [
            {"concept": n.canonical_name, "type": n.type, "relation": e.relation, "arxiv_id": e.arxiv_id}
            for e, n in edges + reverse
        ]
        return result[:limit]
