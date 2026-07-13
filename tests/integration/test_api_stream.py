"""Corpus — API Stream Endpoint Integration Tests."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.retrieval.hybrid_search import RetrievedChunk


@pytest.fixture
def client_with_mocks():
    """Create test client with lifespan/connections mocked."""
    from fastapi import FastAPI
    from src.routers.ask import router

    app = FastAPI()
    app.state.db_session_factory = MagicMock()
    app.state.opensearch = MagicMock()
    app.state.redis = AsyncMock()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


@pytest.mark.asyncio
@patch("src.agents.rag_graph.ask_corpus")
async def test_stream_returns_sse_events(mock_ask, client_with_mocks):
    """Verify that /stream SSE endpoint outputs formatted event streams for trace, tokens, and citations."""
    mock_ask.return_value = {
        "answer_markdown": "Test answer.",
        "citations": [
            {
                "id": 1,
                "paper_title": "Paper Title",
                "arxiv_id": "1234.5678",
                "arxiv_url": "https://arxiv.org/abs/1234.5678",
                "pdf_url": "https://arxiv.org/pdf/1234.5678",
                "section": "Intro",
                "snippet": "A snippet.",
            }
        ],
        "grounding_note": "1 claim verified",
        "trace_events": ["starting query classification", "classification complete"],
        "query_type": "simple",
    }

    payload = {"query": "Complexity of SSMs"}

    response = client_with_mocks.post("/api/v1/stream", json=payload)
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]

    lines = response.text.split("\n\n")

    # Filter out empty lines
    event_lines = [line.strip() for line in lines if line.strip()]

    # We expect event types: trace, token, citation, done
    events = []
    for el in event_lines:
        lines_in_el = el.split("\n")
        event_type = ""
        event_data = None
        for line in lines_in_el:
            if line.startswith("event:"):
                event_type = line.replace("event:", "").strip()
            elif line.startswith("data:"):
                event_data = json.loads(line.replace("data:", "").strip())
        if event_type:
            events.append((event_type, event_data))

    # Verify order and presence
    assert len(events) >= 5
    assert events[0][0] == "trace"  # Initial trace

    # Ensure traces streamed
    trace_events = [e for e in events if e[0] == "trace"]
    assert len(trace_events) >= 3

    # Ensure tokens streamed
    token_events = [e for e in events if e[0] == "token"]
    assert len(token_events) > 0
    assert "".join([t[1]["text"] for t in token_events]) == "Test answer."

    # Ensure citation streamed
    citation_events = [e for e in events if e[0] == "citation"]
    assert len(citation_events) == 1
    assert citation_events[0][1]["arxiv_id"] == "1234.5678"

    # Ensure done event matches shape
    done_event = [e for e in events if e[0] == "done"]
    assert len(done_event) == 1
    assert done_event[0][1]["answer_markdown"] == "Test answer."
    assert done_event[0][1]["grounding_note"] == "1 claim verified"
