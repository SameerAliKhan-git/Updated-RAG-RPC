"""Corpus — API Routes (ask, search, papers).

Endpoints:
  POST /api/v1/ask-agentic  — Full agentic RAG pipeline, structured JSON response.
  POST /api/v1/stream       — SSE streaming of trace events + answer tokens + citations.
  POST /api/v1/search       — Direct hybrid search (bypasses agentic layer).
  GET  /api/v1/papers       — List ingested papers.
  GET  /api/v1/papers/{id}  — Paper detail with chunks.
"""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from src.dependencies import get_db_session, get_opensearch, get_redis
from src.middleware.auth import verify_api_key
from src.middleware.rate_limiter import rate_limiter
from src.services.guardrails import sanitize_query
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

    query, _flags = sanitize_query(body.query)
    toolkit, search_service, reranker = _build_toolkit(db_session, opensearch, redis)
    session_id = body.session_id or str(uuid.uuid4())
    conversation_history = await _load_history(redis, body.session_id, session_id)

    try:
        # Semantic cache: only for fresh (non-follow-up) questions
        cached, query_embedding = await _semantic_cache_lookup(
            redis, search_service, query, conversation_history
        )
        if cached is not None:
            return AgenticResponse(**{**cached, "session_id": session_id, "cached": True})

        result = await ask_corpus(
            query=query,
            toolkit=toolkit,
            session_id=session_id,
            conversation_history=conversation_history,
            filters=body.filters,
        )

        response = AgenticResponse(
            answer_markdown=result.get("answer_markdown", ""),
            citations=[_to_citation(c) for c in result.get("citations", [])],
            grounding_note=result.get("grounding_note", ""),
            query_type=result.get("query_type", ""),
            session_id=session_id,
            trace_events=result.get("trace_events", []),
        )

        await _semantic_cache_store(redis, query, query_embedding, result)
        return response
    finally:
        await search_service.close()
        await reranker.close()


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
    """Stream the agentic RAG pipeline via Server-Sent Events.

    Tokens are emitted live as the LLM generates them; trace events arrive
    per-node as the graph executes. The final `done` event carries the
    post-verification answer — clients reconcile by replacing streamed content.
    """

    async def event_generator():
        from src.agents.rag_graph import ask_corpus_streaming

        query, _flags = sanitize_query(body.query)
        toolkit, search_service, reranker = _build_toolkit(db_session, opensearch, redis)
        session_id = body.session_id or str(uuid.uuid4())
        conversation_history = await _load_history(redis, body.session_id, session_id)

        yield _sse_event("trace", {"step": "starting agentic pipeline..."})

        try:
            # Semantic cache: replay a cached answer instantly for near-duplicate questions
            cached, query_embedding = await _semantic_cache_lookup(
                redis, search_service, query, conversation_history
            )
            if cached is not None:
                yield _sse_event("trace", {"step": "semantic cache hit — serving cached answer"})
                yield _sse_event("token", {"text": cached.get("answer_markdown", "")})
                for citation in cached.get("citations", []):
                    yield _sse_event("citation", citation)
                yield _sse_event("done", {**cached, "session_id": session_id, "cached": True})
                return

            result = None
            async for event in ask_corpus_streaming(
                query=query,
                toolkit=toolkit,
                session_id=session_id,
                conversation_history=conversation_history,
                filters=body.filters,
            ):
                etype = event.get("type")
                if etype == "trace":
                    yield _sse_event("trace", {"step": event.get("step", "")})
                elif etype == "token":
                    yield _sse_event("token", {"text": event.get("text", "")})
                elif etype == "error":
                    yield _sse_event("error", {"message": event.get("message", "")})
                elif etype == "done":
                    result = event.get("result", {})

            if result is not None:
                for citation in result.get("citations", []):
                    yield _sse_event("citation", citation)
                yield _sse_event(
                    "done",
                    {
                        "answer_markdown": result.get("answer_markdown", ""),
                        "citations": result.get("citations", []),
                        "grounding_note": result.get("grounding_note", ""),
                        "query_type": result.get("query_type", ""),
                        "session_id": session_id,
                        "cached": False,
                    },
                )
                await _semantic_cache_store(redis, query, query_embedding, result)

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
    search: str | None = None,
    db_session=Depends(get_db_session),
):
    """List all ingested papers with pagination and optional text search."""
    from sqlalchemy import String as SqlString
    from sqlalchemy import cast, desc, func

    from src.models.paper import Chunk, Paper

    query_builder = db_session.query(Paper)
    if search:
        search_term = f"%{search}%"
        query_builder = query_builder.filter(
            Paper.title.ilike(search_term)
            | Paper.abstract.ilike(search_term)
            | cast(Paper.authors, SqlString).ilike(search_term)
            | cast(Paper.categories, SqlString).ilike(search_term)
        )

    total = query_builder.count()
    offset = (page - 1) * per_page

    papers = query_builder.order_by(desc(Paper.published_date)).offset(offset).limit(per_page).all()

    summaries = []
    for p in papers:
        chunk_count = db_session.query(func.count(Chunk.id)).filter(Chunk.paper_id == p.id).scalar() or 0
        summaries.append(
            PaperSummary(
                arxiv_id=p.arxiv_id,
                title=p.title,
                authors=p.authors if p.authors else [],
                abstract=p.abstract[:300] if p.abstract else "",
                published_date=str(p.published_date) if p.published_date else "",
                categories=p.categories if p.categories else [],
                pdf_processed=p.pdf_processed,
                chunk_count=chunk_count,
            )
        )

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


# ── GET /papers/{arxiv_id}/pdf ──────────────────────────────────


@router.get(
    "/papers/{arxiv_id}/pdf",
    summary="Serve a paper's PDF for the in-app viewer",
)
async def get_paper_pdf(
    arxiv_id: str,
    db_session=Depends(get_db_session),
):
    """Stream the locally cached PDF; fall back to redirecting to the arXiv copy."""
    from pathlib import Path

    from fastapi.responses import FileResponse, RedirectResponse

    from src.config import get_settings
    from src.models.paper import Paper

    safe_id = arxiv_id.replace("/", "_")
    if ".." in safe_id or "\\" in safe_id:
        raise HTTPException(status_code=400, detail="Invalid paper id.")

    pdf_path = Path(get_settings().arxiv.pdf_cache_dir) / f"{safe_id}.pdf"
    if pdf_path.exists():
        return FileResponse(
            pdf_path,
            media_type="application/pdf",
            content_disposition_type="inline",
            filename=f"{safe_id}.pdf",
        )

    paper = db_session.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
    if paper and str(paper.pdf_url).startswith("http"):
        return RedirectResponse(paper.pdf_url)
    raise HTTPException(status_code=404, detail=f"No PDF available for {arxiv_id}.")


# ── POST /papers/extract-metadata ────────────────────────────────


@router.post(
    "/papers/extract-metadata",
    summary="Extract metadata (title, authors, abstract) from an uploaded PDF",
)
async def extract_metadata(
    file: UploadFile = File(...),
):
    """Parse first page of PDF and return extracted title, authors, abstract."""
    import tempfile
    from pathlib import Path

    from src.ingestion.pdf_parser import DoclingParserService

    temp_dir = tempfile.gettempdir()
    temp_path = Path(temp_dir) / (file.filename or "upload.pdf")
    try:
        with open(temp_path, "wb") as f:
            f.write(await file.read())

        parser = DoclingParserService()
        metadata = parser.extract_metadata(temp_path)
        return {
            "title": metadata.get("title", ""),
            "authors": metadata.get("authors", []),
            "abstract": metadata.get("abstract", ""),
        }
    except Exception as e:
        logger.error(f"Metadata extraction failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Metadata extraction failed: {str(e)}") from e
    finally:
        import contextlib

        with contextlib.suppress(Exception):
            if temp_path.exists():
                temp_path.unlink()


# ── POST /papers/upload ──────────────────────────────────────────


@router.post(
    "/papers/upload",
    summary="Upload and ingest a custom PDF paper",
)
async def upload_paper(
    file: UploadFile = File(...),
    title: str = Form(""),
    authors: str = Form(""),
    abstract: str = Form(""),
    categories: str = Form(""),
    db_session=Depends(get_db_session),
    opensearch=Depends(get_opensearch),
):
    """Parse and index an uploaded PDF paper.

    Title and authors are optional — if omitted, they will be auto-extracted
    from the PDF's first page using layout analysis.
    """
    import tempfile
    from pathlib import Path

    from src.ingestion.orchestrator import IngestionOrchestrator

    # Save to temp file
    temp_dir = tempfile.gettempdir()
    temp_path = Path(temp_dir) / (file.filename or "upload.pdf")
    try:
        with open(temp_path, "wb") as f:
            f.write(await file.read())

        # Auto-extract metadata if title or authors not provided
        if not title.strip() or not authors.strip():
            from src.ingestion.pdf_parser import DoclingParserService

            parser = DoclingParserService()
            extracted = parser.extract_metadata(temp_path)
            if not title.strip():
                title = extracted.get("title", "Untitled Document")
            if not authors.strip():
                authors = ", ".join(extracted.get("authors", ["Unknown Author"]))
            if not abstract.strip():
                abstract = extracted.get("abstract", "")

        # Clean author/category formatting
        author_list = [a.strip() for a in authors.split(",") if a.strip()]
        category_list = [c.strip() for c in categories.split(",") if c.strip()]

        orchestrator = IngestionOrchestrator(db_session, opensearch)
        stats = await orchestrator.ingest_local_pdf(
            pdf_path=temp_path,
            title=title,
            authors=author_list,
            abstract=abstract,
            categories=category_list,
        )
        return {"status": "success", "stats": stats}
    except Exception as e:
        logger.error(f"Failed to ingest uploaded paper: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e
    finally:
        import contextlib

        # Clean up temp file
        with contextlib.suppress(Exception):
            if temp_path.exists():
                temp_path.unlink()


# ── Helpers ──────────────────────────────────────────────────────


def _sse_event(event_type: str, data: dict) -> str:
    """Format a Server-Sent Event."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _build_toolkit(db_session, opensearch, redis):
    """Construct the per-request agent toolkit plus the services that need closing."""
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
    return toolkit, search_service, reranker


async def _load_history(redis, provided_session_id: str | None, session_id: str) -> list[dict[str, str]]:
    """Load conversation history for an existing session."""
    if not provided_session_id or not redis:
        return []
    try:
        stored = await redis.get(f"corpus:session:{session_id}")
        if stored:
            return json.loads(stored)
    except Exception as e:
        logger.warning(f"Failed to load session: {e}")
    return []


def _to_citation(c: dict) -> Citation:
    """Map a raw citation dict from the graph onto the API schema."""
    return Citation(
        id=c.get("id", 0),
        paper_title=c.get("paper_title", ""),
        authors=c.get("authors", []),
        arxiv_id=c.get("arxiv_id", ""),
        arxiv_url=c.get("arxiv_url", ""),
        pdf_url=c.get("pdf_url", ""),
        section=c.get("section", ""),
        snippet=c.get("snippet", ""),
    )


async def _semantic_cache_lookup(
    redis, search_service, query: str, conversation_history: list
) -> tuple[dict | None, list[float] | None]:
    """Check the semantic cache for a near-duplicate fresh question.

    Returns (cached_response, query_embedding). Follow-ups are context-dependent
    and are never served from cache. The embedding is returned for reuse when
    storing the eventual answer.
    """
    from src.config import get_settings
    from src.services.redis_services import RedisServicesManager

    settings = get_settings()
    if not settings.semantic_cache_enabled or redis is None or conversation_history:
        return None, None

    try:
        from src.middleware.metrics import SEMANTIC_CACHE_HITS, SEMANTIC_CACHE_MISSES

        query_embedding = await search_service.embeddings_client.embed_query(query)
        cached = await RedisServicesManager(redis).get_semantic_cache(
            query_embedding, threshold=settings.semantic_cache_threshold
        )
        (SEMANTIC_CACHE_HITS if cached is not None else SEMANTIC_CACHE_MISSES).inc()
        return cached, query_embedding
    except Exception as e:
        logger.warning(f"Semantic cache lookup failed: {e}")
        return None, None


async def _semantic_cache_store(redis, query: str, query_embedding: list[float] | None, result: dict) -> None:
    """Persist a successful, non-casual answer to the semantic cache."""
    if redis is None or query_embedding is None:
        return
    if result.get("query_type") == "casual" or not result.get("answer_markdown"):
        return
    try:
        from src.services.redis_services import RedisServicesManager

        await RedisServicesManager(redis).set_semantic_cache(
            query=query,
            query_embedding=query_embedding,
            response={
                "answer_markdown": result.get("answer_markdown", ""),
                "citations": result.get("citations", []),
                "grounding_note": result.get("grounding_note", ""),
                "query_type": result.get("query_type", ""),
                "trace_events": result.get("trace_events", []),
            },
        )
    except Exception as e:
        logger.warning(f"Semantic cache store failed: {e}")
