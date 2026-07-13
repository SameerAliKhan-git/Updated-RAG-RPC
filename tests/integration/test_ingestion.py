from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.postgres import Base
from src.ingestion.interfaces import PaperMetadata
from src.ingestion.orchestrator import IngestionOrchestrator
from src.ingestion.pdf_parser import ParsedDocument, ParsedSection
from src.models.paper import Chunk, Paper


class MockPaperMetadata(PaperMetadata):
    """Mock implementation of PaperMetadata for tests."""

    @property
    def paper_id(self) -> str:
        return "1234.5678"

    @property
    def title(self) -> str:
        return "Mock Paper Title"

    @property
    def authors(self) -> list[str]:
        return ["Author A", "Author B"]

    @property
    def abstract(self) -> str:
        return "This is a mock paper abstract."

    @property
    def published_date(self):
        from datetime import datetime, timezone

        return datetime(2026, 1, 1, tzinfo=timezone.utc)

    @property
    def categories(self) -> list[str]:
        return ["cs.AI"]

    @property
    def pdf_url(self) -> str:
        return "https://arxiv.org/pdf/1234.5678.pdf"


@pytest.mark.asyncio
async def test_ingestion_orchestrator_pipeline():
    """Verify the end-to-end ingestion pipeline writes to DB and calls OpenSearch."""
    # 1. Setup in-memory SQLite database for testing PostgreSQL models
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # 2. Mock external dependencies
    mock_opensearch = MagicMock()
    # Mock search pipeline put
    mock_opensearch.http.put = MagicMock(return_value=None)
    mock_opensearch.indices.exists = MagicMock(return_value=False)
    mock_opensearch.indices.create = MagicMock(return_value=None)

    # 3. Create orchestrator and patch its clients
    orchestrator = IngestionOrchestrator(session, mock_opensearch)

    # Mock fetcher to return one mock paper
    mock_paper = MockPaperMetadata()
    orchestrator.source.fetch_recent_papers = AsyncMock(return_value=[mock_paper])
    orchestrator.source.download_pdf = AsyncMock(return_value="/tmp/mock_paper.pdf")

    # Mock parser to return a structured document
    mock_parsed_doc = ParsedDocument(
        sections=[ParsedSection(title="Section 1", text="Sentence one. Sentence two.")],
        elements=[],
        raw_text="Full text",
    )
    orchestrator.parser.parse = MagicMock(return_value=mock_parsed_doc)

    # Mock Jina Embeddings
    orchestrator.embeddings_client.embed_passages = AsyncMock(return_value=[[0.1] * 1024])

    # 4. Trigger Ingestion
    try:
        stats = await orchestrator.ingest_papers(category="cs.AI", limit=1)

        # 5. Assert database records were created
        papers = session.query(Paper).all()
        assert len(papers) == 1
        assert papers[0].arxiv_id == "1234.5678"
        assert papers[0].title == "Mock Paper Title"
        assert papers[0].pdf_processed is True

        chunks = session.query(Chunk).all()
        assert len(chunks) == 1
        assert chunks[0].section_title == "Section 1"
        assert chunks[0].chunk_type == "body"

        # 6. Assert OpenSearch index was called
        assert mock_opensearch.index.call_count == 1
        call_args = mock_opensearch.index.call_args[1]
        assert call_args["id"] == chunks[0].chunk_id
        assert call_args["body"]["arxiv_id"] == "1234.5678"
        assert call_args["body"]["section_title"] == "Section 1"
        assert len(call_args["body"]["embedding"]) == 1024

        # 7. Check stats returned
        assert stats["fetched"] == 1
        assert stats["parsed"] == 1
        assert stats["chunks_created"] == 1
        assert stats["chunks_indexed"] == 1

    finally:
        session.close()
        engine.dispose()
