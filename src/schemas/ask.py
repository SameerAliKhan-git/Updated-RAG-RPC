"""Corpus — API request/response schemas.

Spec-compliant response shapes for /ask-agentic and /stream endpoints.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ── Request Schemas ──────────────────────────────────────────────


class AskRequest(BaseModel):
    """Request body for POST /ask-agentic."""

    query: str = Field(..., min_length=1, max_length=2000, description="The research question to ask.")
    session_id: str | None = Field(None, description="Session ID for multi-turn conversations.")
    filters: dict[str, Any] | None = Field(
        None, description="Optional metadata filters (categories, date_from, date_to, authors, arxiv_id(s), chunk_type)."
    )
    collection_id: str | None = Field(None, description="Scope retrieval to a collection's papers.")
    verify: bool = Field(
        False, description="Run the LLM faithfulness check on this answer (slower; per-claim grounding)."
    )


class SearchRequest(BaseModel):
    """Request body for POST /search."""

    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=10, ge=1, le=50)
    filter_arxiv_id: str | None = None
    filter_chunk_type: str | None = None
    filter_categories: list[str] | None = None
    filter_authors: list[str] | None = None
    filter_date_from: str | None = None
    filter_date_to: str | None = None


class PaperUpdateRequest(BaseModel):
    """Request body for PATCH /papers/{arxiv_id} (reading tracker)."""

    reading_status: str | None = Field(None, pattern="^(unread|to_read|reading|done)$")
    notes: str | None = Field(None, max_length=10000)


class FeedbackRequest(BaseModel):
    """Request body for POST /feedback."""

    query_id: str = Field(..., description="ID of the query being rated.")
    rating: str = Field(..., pattern="^(up|down)$", description="Thumbs up or down.")
    correction: str | None = Field(None, max_length=2000, description="Optional correction text.")
    trace_id: str | None = Field(None, description="Langfuse trace ID for linking.")


# ── Response Schemas ─────────────────────────────────────────────


class Citation(BaseModel):
    """A single citation in the API response."""

    id: int
    paper_title: str
    authors: list[str] = Field(default_factory=list)
    arxiv_id: str
    arxiv_url: str
    pdf_url: str
    section: str
    snippet: str
    page: int | None = None
    score: float = 0.0


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
    citations: list[Citation] = Field(default_factory=list)
    grounding_note: str = ""
    query_type: str = ""
    session_id: str = ""
    trace_events: list[str] = Field(default_factory=list)
    cached: bool = False
    verification: dict[str, Any] | None = None


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
    results: list[SearchResult]
    total: int


class StreamEvent(BaseModel):
    """A single Server-Sent Event for the /stream endpoint."""

    event: str  # "trace", "token", "citation", "done", "error"
    data: dict[str, Any]


class PaperSummary(BaseModel):
    """Paper summary for list endpoints."""

    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str = ""
    published_date: str = ""
    categories: list[str] = Field(default_factory=list)
    pdf_processed: bool = False
    chunk_count: int = 0
    reading_status: str = "unread"
    notes: str | None = None


class PaperListResponse(BaseModel):
    """Response from GET /papers."""

    papers: list[PaperSummary]
    total: int
    page: int
    per_page: int
