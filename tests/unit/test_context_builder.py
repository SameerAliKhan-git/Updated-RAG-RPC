"""Corpus — Context Builder Unit Tests."""

from __future__ import annotations

from src.retrieval.context_builder import build_citation_context
from src.retrieval.hybrid_search import RetrievedChunk


def test_build_citation_context_formatting():
    """Verify that build_citation_context formats context with [N] tags and resolves metadata."""
    chunks = [
        RetrievedChunk(
            chunk_id="c1",
            arxiv_id="1234.5678",
            paper_id="p1",
            section_title="Introduction",
            chunk_type="body",
            text="This is a sentence about self-attention.",
            title="Transformer Paper",
            authors=["Author A"],
            abstract="Abstract here",
            categories=["cs.LG"],
            published_date="2026-01-01",
            score=0.9,
        ),
        RetrievedChunk(
            chunk_id="c2",
            arxiv_id="8765.4321",
            paper_id="p2",
            section_title="Conclusion",
            chunk_type="body",
            text="This is a sentence about linear-time SSMs.",
            title="Mamba Paper",
            authors=["Author B"],
            abstract="Abstract here",
            categories=["cs.CL"],
            published_date="2026-01-02",
            score=0.85,
        ),
    ]

    ctx = build_citation_context(chunks, max_chunks=2)

    assert "--- Source [1] ---" in ctx.context_str
    assert "--- Source [2] ---" in ctx.context_str
    assert "arXiv:1234.5678" in ctx.context_str
    assert "arXiv:8765.4321" in ctx.context_str

    assert len(ctx.citations) == 2
    assert ctx.citations[0].citation_id == 1
    assert ctx.citations[0].chunk_id == "c1"
    assert ctx.citations[0].section == "Introduction"
    assert ctx.citations[0].paper_title == "Transformer Paper"

    assert ctx.chunk_ids_in_context == ["c1", "c2"]
