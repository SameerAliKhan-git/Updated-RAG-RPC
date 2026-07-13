"""Corpus — API request/response schemas.

Spec-compliant response shapes for /ask-agentic and /stream endpoints.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Request Schemas ──────────────────────────────────────────────


class AskRequest(BaseModel):
    """Request body for POST /ask-agentic."""

    query: str = Field(..., min_length=1, max_length=2000, description="The research question to ask.")
    session_id: Optional[str] = Field(None, description="Session ID for multi-turn conversations.")
    filters: Optional[Dict[str, Any]] = Field(None, description="Optional metadata filters (categories, date_from, date_to, authors).")


class SearchRequest(BaseModel):
    """Request body for POST /search."""

    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=10, ge=1, le=50)
    filter_arxiv_id: Optional[str] = None
    filter_chunk_type: Optional[str] = None
    filter_categories: Optional[List[str]] = None
    filter_authors: Optional[List[str]] = None
    filter_date_from: Optional[str] = None
    filter_date_to: Optional[str] = None


class FeedbackRequest(BaseModel):
    """Request body for POST /feedback."""

    query_id: str = Field(..., description="ID of the query being rated.")
    rating: str = Field(..., pattern="^(up|down)$", description="Thumbs up or down.")
    correction: Optional[str] = Field(None, max_length=2000, description="Optional correction text.")
    trace_id: Optional[str] = Field(None, description="Langfuse trace ID for linking.")


# ── Response Schemas ─────────────────────────────────────────────


class Citation(BaseModel):
    """A single citation in the API response."""

    id: int
    paper_title: str
    authors: List[str] = Field(default_factory=list)
    arxiv_id: str
    arxiv_url: str
    pdf_url: str
    section: str
    snippet: str


class AgenticResponse(BaseModel):
    """Structured response from POST /ask-agentic.

    Matches the spec's required shape:
    {
        "answer_markdown": "... claim [1] ... claim [2] ...",
        "citations": [...],
        "grounding_note": "2 of 2 claims verified against source"
    }
    """

    answer_markdown: str
    citations: List[Citation] = Field(default_factory=list)
    grounding_note: str = ""
    query_type: str = ""
    session_id: str = ""
    trace_events: List[str] = Field(default_factory=list)


class SearchResult(BaseModel):
    """A single search result from POST /search."""

    chunk_id: str
    arxiv_id: str
    paper_title: str
    section_title: str
    chunk_type: str
    text: str
    score: float
    citation: str


class SearchResponse(BaseModel):
    """Response from POST /search."""

    query: str
    results: List[SearchResult]
    total: int


class StreamEvent(BaseModel):
    """A single Server-Sent Event for the /stream endpoint."""

    event: str  # "trace", "token", "citation", "done", "error"
    data: Dict[str, Any]


class PaperSummary(BaseModel):
    """Paper summary for list endpoints."""

    arxiv_id: str
    title: str
    authors: List[str]
    abstract: str = ""
    published_date: str = ""
    categories: List[str] = Field(default_factory=list)
    pdf_processed: bool = False
    chunk_count: int = 0


class PaperListResponse(BaseModel):
    """Response from GET /papers."""

    papers: List[PaperSummary]
    total: int
    page: int
    per_page: int
