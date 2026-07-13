"""Corpus — API Routes (ask, search, papers).

Endpoints:
  POST /api/v1/ask-agentic  — Full agentic RAG pipeline, structured JSON response.
  POST /api/v1/stream       — SSE streaming of trace events + answer tokens + citations.
  POST /api/v1/search       — Direct hybrid search (bypasses agentic layer).
  GET  /api/v1/papers       — List ingested papers.
  GET  /api/v1/papers/{id}  — Paper detail with chunks.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.dependencies import get_db_session, get_opensearch, get_redis
from src.middleware.auth import verify_api_key
from src.middleware.rate_limiter import rate_limiter
from src.schemas.ask import (
    AgenticResponse,
    AskRequest,
    Citation,
    PaperListResponse,
    PaperSummary,
    SearchRequest,
    SearchResponse,
    SearchResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["corpus"],
    dependencies=[Depends(verify_api_key)],
)


# ── POST /ask-agentic ───────────────────────────────────────────


@router.post(
    "/ask-agentic",
    response_model=AgenticResponse,
    summary="Full agentic RAG pipeline",
    description="Runs the complete agentic loop: route → plan → retrieve → grade → rerank → generate → verify. Returns structured JSON with answer + citations.",
    dependencies=[Depends(rate_limiter)],
)
async def ask_agentic(
    body: AskRequest,
    request: Request,
    db_session=Depends(get_db_session),
    opensearch=Depends(get_opensearch),
    redis=Depends(get_redis),
):
    """Run the full agentic RAG pipeline."""
    from src.agents.rag_graph import ask_corpus
    from src.agents.tools import AgentToolkit
    from src.retrieval.hybrid_search import HybridSearchService
    from src.retrieval.reranker import create_reranker

    # Build the toolkit for this request
    search_service = HybridSearchService(opensearch)
    reranker = create_reranker()
    toolkit = AgentToolkit(
        search_service=search_service,
        reranker=reranker,
        db_session=db_session,
        redis_client=redis,
    )

    # Load session history from Redis if session_id provided
    conversation_history = []
    session_id = body.session_id or str(uuid.uuid4())
    if body.session_id and redis:
        try:
            stored = await redis.get(f"corpus:session:{session_id}")
            if stored:
                conversation_history = json.loads(stored)
        except Exception as e:
            logger.warning(f"Failed to load session: {e}")

    result = await ask_corpus(
        query=body.query,
        toolkit=toolkit,
        session_id=session_id,
        conversation_history=conversation_history,
    )

    # Build response
    citations = []
    for c in result.get("citations", []):
        citations.append(Citation(
            id=c.get("id", 0),
            paper_title=c.get("paper_title", ""),
            authors=c.get("authors", []),
            arxiv_id=c.get("arxiv_id", ""),
            arxiv_url=c.get("arxiv_url", ""),
            pdf_url=c.get("pdf_url", ""),
            section=c.get("section", ""),
            snippet=c.get("snippet", ""),
        ))

    # Clean up
    await search_service.close()
    await reranker.close()

    return AgenticResponse(
        answer_markdown=result.get("answer_markdown", ""),
        citations=citations,
        grounding_note=result.get("grounding_note", ""),
        query_type=result.get("query_type", ""),
        session_id=session_id,
        trace_events=result.get("trace_events", []),
    )


# ── POST /stream ────────────────────────────────────────────────


@router.post(
    "/stream",
    summary="SSE streaming endpoint",
    description="Streams trace events, answer tokens, and citations as Server-Sent Events.",
    dependencies=[Depends(rate_limiter)],
)
async def stream_ask(
    body: AskRequest,
    request: Request,
    db_session=Depends(get_db_session),
    opensearch=Depends(get_opensearch),
    redis=Depends(get_redis),
):
    """Stream the agentic RAG pipeline via Server-Sent Events."""

    async def event_generator():
        from src.agents.rag_graph import ask_corpus
        from src.agents.tools import AgentToolkit
        from src.retrieval.hybrid_search import HybridSearchService
        from src.retrieval.reranker import create_reranker

        search_service = HybridSearchService(opensearch)
        reranker = create_reranker()
        toolkit = AgentToolkit(
            search_service=search_service,
            reranker=reranker,
            db_session=db_session,
            redis_client=redis,
        )

        session_id = body.session_id or str(uuid.uuid4())
        conversation_history = []
        if body.session_id and redis:
            try:
                stored = await redis.get(f"corpus:session:{session_id}")
                if stored:
                    conversation_history = json.loads(stored)
            except Exception:
                pass

        # Send initial event
        yield _sse_event("trace", {"step": "starting agentic pipeline..."})

        try:
            result = await ask_corpus(
                query=body.query,
                toolkit=toolkit,
                session_id=session_id,
                conversation_history=conversation_history,
            )

            # Stream trace events
            for trace in result.get("trace_events", []):
                yield _sse_event("trace", {"step": trace})
                await asyncio.sleep(0.05)  # Small delay for SSE client rendering

            # Stream the answer
            answer = result.get("answer_markdown", "")
            # Send in chunks of ~50 chars for streaming effect
            for i in range(0, len(answer), 50):
                chunk = answer[i : i + 50]
                yield _sse_event("token", {"text": chunk})
                await asyncio.sleep(0.02)

            # Stream citations
            for citation in result.get("citations", []):
                yield _sse_event("citation", citation)

            # Final done event with full response
            yield _sse_event("done", {
                "answer_markdown": answer,
                "citations": result.get("citations", []),
                "grounding_note": result.get("grounding_note", ""),
                "query_type": result.get("query_type", ""),
                "session_id": session_id,
            })

        except Exception as e:
            logger.error(f"Stream error: {e}", exc_info=True)
            yield _sse_event("error", {"message": str(e)})

        finally:
            await search_service.close()
            await reranker.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── POST /search ────────────────────────────────────────────────


@router.post(
    "/search",
    response_model=SearchResponse,
    summary="Direct hybrid search",
    description="Bypasses the agentic layer — direct BM25 + vector + RRF search.",
)
async def search(
    body: SearchRequest,
    opensearch=Depends(get_opensearch),
):
    """Direct hybrid search — bypasses the agentic layer."""
    from src.retrieval.hybrid_search import HybridSearchService

    service = HybridSearchService(opensearch)
    try:
        chunks = await service.search(
            query=body.query,
            top_k=body.top_k,
            filter_arxiv_id=body.filter_arxiv_id,
            filter_chunk_type=body.filter_chunk_type,
            filter_categories=body.filter_categories,
            filter_authors=body.filter_authors,
            filter_date_from=body.filter_date_from,
            filter_date_to=body.filter_date_to,
        )

        results = [
            SearchResult(
                chunk_id=c.chunk_id,
                arxiv_id=c.arxiv_id,
                paper_title=c.title,
                section_title=c.section_title,
                chunk_type=c.chunk_type,
                text=c.text[:500],
                score=c.score,
                citation=c.citation,
            )
            for c in chunks
        ]

        return SearchResponse(query=body.query, results=results, total=len(results))
    finally:
        await service.close()


# ── GET /papers ─────────────────────────────────────────────────


@router.get(
    "/papers",
    response_model=PaperListResponse,
    summary="List ingested papers",
)
async def list_papers(
    page: int = 1,
    per_page: int = 20,
    db_session=Depends(get_db_session),
):
    """List all ingested papers with pagination."""
    from sqlalchemy import desc, func

    from src.models.paper import Chunk, Paper

    total = db_session.query(func.count(Paper.id)).scalar() or 0
    offset = (page - 1) * per_page

    papers = (
        db_session.query(Paper)
        .order_by(desc(Paper.published_date))
        .offset(offset)
        .limit(per_page)
        .all()
    )

    summaries = []
    for p in papers:
        chunk_count = db_session.query(func.count(Chunk.id)).filter(Chunk.paper_id == p.id).scalar() or 0
        summaries.append(PaperSummary(
            arxiv_id=p.arxiv_id,
            title=p.title,
            authors=p.authors if p.authors else [],
            abstract=p.abstract[:300] if p.abstract else "",
            published_date=str(p.published_date) if p.published_date else "",
            categories=p.categories if p.categories else [],
            pdf_processed=p.pdf_processed,
            chunk_count=chunk_count,
        ))

    return PaperListResponse(papers=summaries, total=total, page=page, per_page=per_page)


# ── GET /papers/{arxiv_id} ──────────────────────────────────────


@router.get(
    "/papers/{arxiv_id}",
    summary="Paper detail",
)
async def get_paper(
    arxiv_id: str,
    db_session=Depends(get_db_session),
):
    """Get full paper details including chunks."""
    from src.models.paper import Chunk, Paper

    paper = db_session.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail=f"Paper {arxiv_id} not found.")

    chunks = db_session.query(Chunk).filter(Chunk.paper_id == paper.id).all()

    return {
        "arxiv_id": paper.arxiv_id,
        "title": paper.title,
        "authors": paper.authors,
        "abstract": paper.abstract,
        "published_date": str(paper.published_date) if paper.published_date else None,
        "categories": paper.categories,
        "pdf_url": paper.pdf_url,
        "pdf_processed": paper.pdf_processed,
        "chunk_count": len(chunks),
        "chunks": [
            {
                "chunk_id": c.chunk_id,
                "section_title": c.section_title,
                "chunk_type": c.chunk_type,
                "text": c.text[:300],
                "chunk_index": c.chunk_index,
            }
            for c in chunks
        ],
    }


# ── Helpers ──────────────────────────────────────────────────────


def _sse_event(event_type: str, data: dict) -> str:
    """Format a Server-Sent Event."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
