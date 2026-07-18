"""Corpus — Mock API Server for Frontend UI Verification.

Launches the FastAPI server with mocked databases and LLM adapters,
allowing full UI verification when Docker services are not active locally.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Add project root to path
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Mock the database, opensearch, and redis startup functions BEFORE importing main
mock_redis_client = AsyncMock()
mock_redis_client.ping = AsyncMock(return_value=True)
mock_redis_store = {}


async def mock_get(key: str):
    return mock_redis_store.get(key)


async def mock_set(key: str, val: str):
    mock_redis_store[key] = val
    return True


mock_redis_client.get = AsyncMock(side_effect=mock_get)
mock_redis_client.set = AsyncMock(side_effect=mock_set)

import src.services.redis_client

src.services.redis_client.create_redis_client = AsyncMock(return_value=mock_redis_client)

import src.db.postgres

src.db.postgres.create_engine_and_session = MagicMock(return_value=(MagicMock(), MagicMock()))

import src.db.opensearch

src.db.opensearch.create_opensearch_client = MagicMock(return_value=MagicMock())

# Now we can safely import main and uvicorn
import uvicorn
from fastapi import FastAPI

from src.main import create_app

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def build_mocked_app() -> FastAPI:
    """Create a FastAPI application with database and Redis dependency mocks."""
    app = create_app()

    # Set up mocks in state directly
    app.state.db_engine = MagicMock()
    app.state.db_session_factory = MagicMock()
    app.state.opensearch = MagicMock()
    app.state.redis = mock_redis_client

    return app


# Mock response payload matching UI specs
mock_response = {
    "answer_markdown": """### Architectural Comparison: Mamba vs. Transformers

Selective State Space Models like **Mamba** scale with **linear complexity O(N)** in sequence length [1], overcoming the **quadratic complexity O(N^2)** of standard self-attention mechanisms in **Transformers** [2].

#### Key Performance Metrics Comparison:

| Metric | Mamba (Selective SSM) | Transformers (Self-Attention) |
| :--- | :--- | :--- |
| **Sequence Complexity** | Linear O(N) [1] | Quadratic O(N^2) [2] |
| **State Update** | Recurrent / Constant Time | Dynamic / Dependent on KV-Cache |
| **Throughput** | Up to 5x higher inference speed | Suffers from memory bottleneck at scale |

> "Mamba enjoys 5x higher throughput than Transformers and scales linearly with sequence length, maintaining high quality even down to million-length contexts." [1]

#### Core Mechanisms:
- **Mamba**: Uses a selection mechanism to choose what information to retain or discard at each sequence step, operating like a content-aware recurrent loop [1].
- **Transformers**: Uses dense pairwise attention matrices, comparing every token in the sequence with every other token [2].""",
    "citations": [
        {
            "id": 1,
            "paper_title": "Mamba: Linear-Time Sequence Modeling with Selective State Spaces",
            "authors": ["Albert Gu", "Tri Dao"],
            "arxiv_id": "2312.00752",
            "arxiv_url": "https://arxiv.org/abs/2312.00752",
            "pdf_url": "https://arxiv.org/pdf/2312.00752",
            "section": "Abstract",
            "snippet": "We introduce Selective State Space Models which scale linearly with sequence length.",
        },
        {
            "id": 2,
            "paper_title": "Attention Is All You Need",
            "authors": ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"],
            "arxiv_id": "1706.03762",
            "arxiv_url": "https://arxiv.org/abs/1706.03762",
            "pdf_url": "https://arxiv.org/pdf/1706.03762",
            "section": "Complexity",
            "snippet": "Self-attention layers scale quadratically with sequence length.",
        },
    ],
    "grounding_note": "2 of 2 claims verified against sources",
    "trace_events": [
        "classifying query...",
        "query classified as: simple",
        "decomposing query into sub-questions...",
        "hybrid search (BM25 + vectors)...",
        "2 relevant chunks found",
        "reranking chunks...",
        "building citation context...",
        "generating answer...",
        "verifying citations...",
        "resolving metadata...",
    ],
    "query_type": "simple",
}

mock_papers = {
    "papers": [
        {
            "arxiv_id": "2312.00752",
            "title": "Mamba: Linear-Time Sequence Modeling with Selective State Spaces",
            "authors": ["Albert Gu", "Tri Dao"],
            "abstract": "We present selective state space models scaling linearly with sequence length.",
            "published_date": "2023-12-01",
            "categories": ["cs.LG"],
            "pdf_processed": True,
            "chunk_count": 12,
        },
        {
            "arxiv_id": "1706.03762",
            "title": "Attention Is All You Need",
            "authors": ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"],
            "abstract": "We propose the Transformer, a model architecture based entirely on attention mechanisms.",
            "published_date": "2017-06-12",
            "categories": ["cs.CL", "cs.LG"],
            "pdf_processed": True,
            "chunk_count": 24,
        },
        {
            "arxiv_id": "2001.08361",
            "title": "Scaling Laws for Neural Language Models",
            "authors": ["Jared Kaplan", "Sam McCandlish", "Tom Henighan"],
            "abstract": "We study empirical scaling laws for language model performance on the cross-entropy loss.",
            "published_date": "2020-01-23",
            "categories": ["cs.LG", "cs.CL"],
            "pdf_processed": True,
            "chunk_count": 18,
        },
        {
            "arxiv_id": "2005.14165",
            "title": "Language Models are Few-Shot Learners",
            "authors": ["Tom Brown", "Benjamin Mann", "Nick Ryder"],
            "abstract": "We show that scaling up language models greatly improves task-agnostic few-shot performance.",
            "published_date": "2020-05-28",
            "categories": ["cs.CL"],
            "pdf_processed": True,
            "chunk_count": 42,
        },
        {
            "arxiv_id": "2203.15556",
            "title": "Training language models to follow instructions with human feedback",
            "authors": ["Long Ouyang", "Jeff Wu", "Xu Jiang"],
            "abstract": "We train language models to follow instructions using reinforcement learning from human feedback.",
            "published_date": "2022-03-04",
            "categories": ["cs.CL", "cs.AI"],
            "pdf_processed": True,
            "chunk_count": 31,
        },
        {
            "arxiv_id": "2302.13971",
            "title": "LLaMA: Open and Efficient Foundation Language Models",
            "authors": ["Hugo Touvron", "Thibaut Lavril", "Gautier Izacard"],
            "abstract": "We introduce LLaMA, a collection of foundation language models ranging from 7B to 65B parameters.",
            "published_date": "2023-02-27",
            "categories": ["cs.CL"],
            "pdf_processed": True,
            "chunk_count": 15,
        },
    ],
    "total": 6,
    "page": 1,
    "per_page": 20,
}


if __name__ == "__main__":
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, HTMLResponse

    # Build a standalone mock app — bypasses all real routers entirely
    mock_app = FastAPI(title="Corpus Mock", version="0.1.0-mock")
    mock_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Health ──
    @mock_app.get("/api/v1/health")
    async def mock_health():
        return {"status": "healthy", "environment": "development", "debug": True}

    # ── Ask Agentic ──
    @mock_app.post("/api/v1/ask-agentic")
    async def mock_ask_agentic(body: dict):
        return mock_response

    # ── SSE Stream ──
    @mock_app.post("/api/v1/stream")
    async def mock_stream(body: dict):
        import asyncio
        import json as _json

        from starlette.responses import StreamingResponse

        async def event_generator():
            # Stream trace events
            for trace in mock_response["trace_events"]:
                yield f"event: trace\ndata: {_json.dumps({'step': trace})}\n\n"
                await asyncio.sleep(0.15)

            # Stream answer tokens
            answer = mock_response["answer_markdown"]
            for i in range(0, len(answer), 50):
                chunk = answer[i : i + 50]
                yield f"event: token\ndata: {_json.dumps({'text': chunk})}\n\n"
                await asyncio.sleep(0.05)

            # Stream citations
            for citation in mock_response["citations"]:
                yield f"event: citation\ndata: {_json.dumps(citation)}\n\n"

            # Done
            yield f"event: done\ndata: {_json.dumps({'answer_markdown': answer, 'citations': mock_response['citations'], 'grounding_note': mock_response['grounding_note'], 'query_type': mock_response['query_type'], 'session_id': 'mock-session-001'})}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    # ── Papers ──
    @mock_app.get("/api/v1/papers")
    async def mock_list_papers(page: int = 1, per_page: int = 20, search: str | None = None):
        all_papers = mock_papers["papers"]
        if search:
            s_lower = search.lower()
            all_papers = [
                p
                for p in all_papers
                if s_lower in p["title"].lower()
                or s_lower in p.get("abstract", "").lower()
                or any(s_lower in a.lower() for a in p["authors"])
                or any(s_lower in c.lower() for c in p["categories"])
            ]
        return {
            "papers": all_papers,
            "total": len(all_papers),
            "page": page,
            "per_page": per_page,
        }

    @mock_app.get("/api/v1/papers/{arxiv_id}")
    async def mock_get_paper(arxiv_id: str):
        for p in mock_papers["papers"]:
            if p["arxiv_id"] == arxiv_id:
                return {**p, "chunks": []}
        return {"detail": "Not found"}

    # ── Eval ──
    @mock_app.post("/api/v1/eval/run")
    async def mock_eval_run():
        import json as _json

        await mock_redis_client.set(
            "corpus:eval:status",
            _json.dumps(
                {
                    "status": "COMPLETED",
                    "timestamp": "2026-07-17T12:00:00Z",
                    "scores": {"faithfulness": 0.92, "answer_relevancy": 0.88},
                }
            ),
        )
        return {"status": "success", "message": "Evaluation job triggered in background."}

    @mock_app.get("/api/v1/eval/status")
    async def mock_eval_status():
        import json as _json

        raw = await mock_redis_client.get("corpus:eval:status")
        if raw:
            return _json.loads(raw)
        return {
            "status": "NOT_RUN",
            "timestamp": None,
            "scores": {"faithfulness": 0.85, "answer_relevancy": 0.88},
        }

    # ── Langfuse Diagnostics ──
    @mock_app.get("/api/v1/diagnostics/langfuse")
    async def mock_langfuse_diagnostics():
        return {
            "status": "INACTIVE",
            "public_key_configured": False,
            "secret_key_configured": False,
            "host": "http://localhost:3001",
        }

    # ── Feedback (stub) ──
    @mock_app.post("/api/v1/feedback")
    async def mock_feedback(body: dict):
        return {"status": "success", "message": "Feedback recorded."}

    # Start uvicorn
    logger.info("Starting mock API server on port 8000...")
    uvicorn.run(mock_app, host="127.0.0.1", port=8000)

