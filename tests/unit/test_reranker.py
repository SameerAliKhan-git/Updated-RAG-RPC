"""Corpus — Reranker Unit Tests."""

from __future__ import annotations

import pytest

from src.retrieval.hybrid_search import RetrievedChunk
from src.retrieval.reranker import NoOpReranker


@pytest.mark.asyncio
async def test_noop_reranker_returns_top_k():
    """Verify that NoOpReranker returns chunks ordered by score capped at top_k."""
    chunks = [
        RetrievedChunk(
            chunk_id="c1", arxiv_id="1", paper_id="p1", section_title="S1", chunk_type="body",
            text="text1", title="T1", authors=["A1"], abstract="abs1", categories=["cat1"],
            published_date="2026-01-01", score=0.5
        ),
        RetrievedChunk(
            chunk_id="c2", arxiv_id="2", paper_id="p2", section_title="S2", chunk_type="body",
            text="text2", title="T2", authors=["A2"], abstract="abs2", categories=["cat2"],
            published_date="2026-01-02", score=0.9
        ),
        RetrievedChunk(
            chunk_id="c3", arxiv_id="3", paper_id="p3", section_title="S3", chunk_type="body",
            text="text3", title="T3", authors=["A3"], abstract="abs3", categories=["cat3"],
            published_date="2026-01-03", score=0.7
        )
    ]

    reranker = NoOpReranker()
    result = await reranker.rerank(query="test", chunks=chunks, top_k=2)

    assert len(result) == 2
    # Should be ordered descending: score 0.9 (c2) then 0.7 (c3)
    assert result[0].chunk_id == "c2"
    assert result[1].chunk_id == "c3"
