"""Corpus — Mock API Server for Frontend UI Verification.

Launches the FastAPI server with mocked databases and LLM adapters,
allowing full UI verification when Docker services are not active locally.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Mock the database, opensearch, and redis startup functions BEFORE importing main
mock_redis_client = AsyncMock()
mock_redis_client.ping = AsyncMock(return_value=True)

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
    "answer_markdown": "Based on the selective state space models [1], Mamba scales with linear complexity O(N) in sequence length, overcoming the quadratic complexity O(N^2) of standard Transformers [2].",
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
        }
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
            "abstract": "We present selective state space models scaling linearly.",
            "published_date": "2023-12-01",
            "categories": ["cs.LG"],
            "pdf_processed": True,
            "chunk_count": 12,
        }
    ],
    "total": 1,
    "page": 1,
    "per_page": 20,
}


if __name__ == "__main__":
    app = build_mocked_app()

    # Direct route overrides to guarantee mock payloads bypass database calls completely
    @app.post("/api/v1/ask-agentic")
    async def mock_ask_agentic(body: dict):
        return mock_response

    @app.get("/api/v1/papers")
    async def mock_list_papers(page: int = 1, per_page: int = 20):
        # Return a larger count to match the spec's zero.xyz look and feel
        return {
            "papers": mock_papers["papers"],
            "total": 12482,
            "page": page,
            "per_page": per_page,
        }

    # Start uvicorn
    logger.info("Starting mock API server on port 8000...")
    uvicorn.run(app, host="127.0.0.1", port=8000)
