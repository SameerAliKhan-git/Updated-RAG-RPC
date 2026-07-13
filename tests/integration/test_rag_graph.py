"""Corpus — Agentic RAG Graph Integration Tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.agents.rag_graph import ask_corpus
from src.retrieval.hybrid_search import RetrievedChunk


@pytest.fixture(autouse=True)
def mock_llms():
    """Mock the reasoning and drafting LLMs for hermetic graph tests."""
    with patch("src.agents.rag_graph.call_reasoning_llm") as mock_reasoning, \
         patch("src.agents.rag_graph.call_drafting_llm") as mock_drafting:

        async def side_effect_reasoning(messages, *args, **kwargs):
            content = messages[0]["content"]
            if "query classifier" in content:
                if "Hello Corpus" in content:
                    return '{"query_type": "casual", "reasoning": "casual query"}'
                return '{"query_type": "simple", "reasoning": "simple query"}'
            elif "relevance grader" in content:
                return '{"relevant": true, "confidence": "high"}'
            elif "citation verification" in content:
                return '{"verified_claims": 1, "total_claims": 1, "issues": [], "grounding_note": "1 claim verified"}'
            return '{}'

        async def side_effect_drafting(messages, *args, **kwargs):
            content = messages[0]["content"]
            if "casual messages" in content:
                return "Hello! I am Corpus, your research paper curator."
            return "Based on the selective state space models, they scale with linear complexity [1]."

        mock_reasoning.side_effect = side_effect_reasoning
        mock_drafting.side_effect = side_effect_drafting
        yield


class MockToolkit:
    """Hermetic mock agent toolkit for graph node integration tests."""

    def __init__(self, search_results=None, live_results=None):
        self.redis = None
        self.search_results = search_results or []
        self.live_results = live_results or []
        self.ingestion_triggered = []

    async def hybrid_search(self, query: str, top_k: int = 15) -> list[RetrievedChunk]:
        return self.search_results

    async def rerank_chunks(self, query: str, chunks: list[RetrievedChunk], top_k: int = 8) -> list[RetrievedChunk]:
        return chunks[:top_k]

    async def get_paper(self, arxiv_id: str) -> dict | None:
        return None

    async def search_arxiv_live(self, query: str, max_results: int = 5) -> list[dict]:
        return self.live_results

    async def trigger_ingestion(self, arxiv_id: str) -> bool:
        self.ingestion_triggered.append(arxiv_id)
        return True

    async def list_recent(self, topic: str = "", n: int = 10) -> list[dict]:
        return []

    async def compare(self, paper_ids: list[str], aspect: str = "") -> dict:
        return {}


@pytest.mark.asyncio
async def test_graph_casual_query_routing():
    """Verify that a greeting query is classified as casual and returns a conversational response."""
    toolkit = MockToolkit()
    # "Hi there" should route to handle_casual
    result = await ask_corpus(query="Hello Corpus, how are you?", toolkit=toolkit)

    assert result["query_type"] == "casual"
    assert len(result["answer_markdown"]) > 5
    assert len(result["citations"]) == 0


@pytest.mark.asyncio
async def test_graph_successful_rag_retrieval_and_generation():
    """Verify standard query returns grounded answer with metadata-matched citations."""
    chunks = [
        RetrievedChunk(
            chunk_id="chunk_1", arxiv_id="2401.0001", paper_id="p1", section_title="Method", chunk_type="body",
            text="We introduce selective state space models showing linear complexity.", title="Selective SSMs",
            authors=["A. Gu", "T. Dao"], abstract="Selective SSMs.", categories=["cs.LG"],
            published_date="2024-01-01", score=0.9
        )
    ]
    toolkit = MockToolkit(search_results=chunks)

    # Grader will judge it relevant, generating citations
    result = await ask_corpus(query="What is the complexity of selective SSMs?", toolkit=toolkit)

    assert result["query_type"] in ("simple", "complex", "followup")
    assert len(result["citations"]) == 1
    assert result["citations"][0]["arxiv_id"] == "2401.0001"
    assert "linear complexity" in result["answer_markdown"] or "SSM" in result["answer_markdown"]


@pytest.mark.asyncio
async def test_graph_empty_index_triggers_live_lookup():
    """Verify that empty index triggers direct live arXiv lookups and queues on-demand ingestion."""
    live_paper = {
        "arxiv_id": "2402.12345",
        "title": "Recent Breakthrough in LLMs",
        "authors": ["Lead Researcher"],
        "abstract": "We present a breakthrough sequence modeling approach.",
        "arxiv_url": "https://arxiv.org/abs/2402.12345",
        "pdf_url": "https://arxiv.org/pdf/2402.12345",
    }
    toolkit = MockToolkit(search_results=[], live_results=[live_paper])

    # No hits in DB -> triggers live lookup -> gets live paper -> triggers ingestion queue
    result = await ask_corpus(query="What is the breakthrough in sequence modeling?", toolkit=toolkit)

    assert len(toolkit.ingestion_triggered) == 1
    assert "2402.12345" in toolkit.ingestion_triggered
    assert len(result["citations"]) == 1
    assert result["citations"][0]["arxiv_id"] == "2402.12345"
