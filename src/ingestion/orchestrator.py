from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opensearchpy import OpenSearch
from sqlalchemy.orm import Session

from src.config import get_settings
from src.db.opensearch import setup_opensearch_indices
from src.ingestion.arxiv_source import ArxivPaperSource
from src.ingestion.chunker import StructureAwareChunker
from src.ingestion.interfaces import PaperMetadata
from src.ingestion.pdf_parser import DoclingParserService, ParsedDocument
from src.models.paper import Chunk, Paper
from src.services.embedding_client import create_embedding_client

logger = logging.getLogger(__name__)


class IngestionOrchestrator:
    """Orchestrates the entire document ingestion workflow: fetch -> parse -> chunk -> embed -> dual-write."""

    def __init__(self, db_session: Session, opensearch_client: OpenSearch):
        self.settings = get_settings()
        self.db_session = db_session
        self.opensearch_client = opensearch_client

        # Initialize integration components
        self.source = ArxivPaperSource()
        self.parser = DoclingParserService()
        self.chunker = StructureAwareChunker()
        self.embeddings_client = create_embedding_client()

        # Local cache path
        self.cache_dir = Path(self.settings.arxiv.pdf_cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def ingest_papers(
        self,
        category: str,
        limit: int = 5,
        specific_arxiv_id: str | None = None,
    ) -> dict[str, Any]:
        """Fetch papers, parse them with Docling, chunk, embed, and index into DB + OpenSearch."""
        stats = {
            "fetched": 0,
            "parsed": 0,
            "chunks_created": 0,
            "chunks_indexed": 0,
            "errors": 0,
        }

        # 1. Setup OpenSearch indices
        setup_opensearch_indices(self.opensearch_client)

        # 2. Fetch papers from category or specific ID
        try:
            if specific_arxiv_id:
                # Fetch a single specific paper
                paper = await self.source.fetch_by_id(specific_arxiv_id)
                papers = [paper] if paper else []
                logger.info(f"Fetched single paper {specific_arxiv_id} directly.")
            else:
                papers = await self.source.fetch_recent_papers(category=category, limit=limit)
            stats["fetched"] = len(papers)
            if not specific_arxiv_id:
                logger.info(f"Fetched {len(papers)} paper entries from arXiv category: {category}")
        except Exception as e:
            logger.error(f"Failed fetching papers from source: {e}")
            stats["errors"] += 1
            return stats

        # 3. Process each paper
        for paper in papers:
            try:
                await self._process_single_paper(paper, stats)
            except Exception as e:
                logger.error(f"Error processing paper {paper.paper_id}: {e}", exc_info=True)
                stats["errors"] += 1

        # Clean up Jina client connections
        await self.embeddings_client.close()
        await self.source.close()

        return stats

    async def ingest_local_pdf(
        self,
        pdf_path: Path,
        title: str,
        authors: list[str],
        abstract: str = "",
        categories: list[str] | None = None,
    ) -> dict[str, Any]:
        """Ingest a local PDF file into PostgreSQL database and OpenSearch."""
        if categories is None:
            categories = []
        stats: dict[str, Any] = {
            "parsed": 0,
            "chunks_created": 0,
            "chunks_indexed": 0,
            "errors": 0,
        }

        # 1. Setup OpenSearch indices
        setup_opensearch_indices(self.opensearch_client)

        # 2. Parse PDF layout via Docling
        try:
            parsed_doc = self.parser.parse(pdf_path)
            stats["parsed"] += 1
        except Exception as e:
            logger.error(f"Docling parsing failed for PDF {pdf_path}: {e}")
            raise e

        # Generate a unique synthetic arxiv_id for uploads
        arxiv_id = f"upload_{int(datetime.now(UTC).timestamp())}"
        stats["arxiv_id"] = arxiv_id

        # Persist the PDF into the cache dir so it can be served in-app later
        import shutil

        cached_pdf = self.cache_dir / f"{arxiv_id}.pdf"
        try:
            shutil.copyfile(pdf_path, cached_pdf)
        except Exception as ex:
            logger.warning(f"Could not persist uploaded PDF {pdf_path}: {ex}")

        # 3. Save Paper metadata in Postgres
        db_paper = Paper(
            arxiv_id=arxiv_id,
            title=title,
            authors=authors,
            abstract=abstract,
            published_date=datetime.now(UTC),
            categories=categories,
            pdf_url=str(cached_pdf.name),
            raw_text=parsed_doc.raw_text,
            pdf_processed=True,
        )
        self.db_session.add(db_paper)
        self.db_session.commit()
        self.db_session.refresh(db_paper)

        # 4. Chunk layout structure
        chunks = self.chunker.chunk_document(parsed_doc, str(db_paper.id), arxiv_id)
        stats["chunks_created"] += len(chunks)

        # 5. Generate Jina v4 embeddings
        chunk_texts = [c.text for c in chunks]
        embeddings = await self.embeddings_client.embed_passages(chunk_texts)

        # 6. Write to PostgreSQL and index in OpenSearch
        index_name = self.settings.opensearch.chunk_index_name

        for idx, chunk in enumerate(chunks):
            # Save Chunk in PostgreSQL
            db_chunk = Chunk(
                chunk_id=chunk.chunk_id,
                paper_id=db_paper.id,
                arxiv_id=chunk.arxiv_id,
                section_title=chunk.section_title,
                chunk_type=chunk.chunk_type,
                text=chunk.text,
                page_number=chunk.page_number,
            )
            self.db_session.add(db_chunk)

            # Index in OpenSearch
            doc = {
                "chunk_id": chunk.chunk_id,
                "arxiv_id": chunk.arxiv_id,
                "paper_id": str(db_paper.id),
                "section_title": chunk.section_title,
                "chunk_type": chunk.chunk_type,
                "text": chunk.text,
                "page_number": chunk.page_number,
                "embedding": embeddings[idx],
                "title": title,
                "authors": authors,
                "abstract": abstract,
                "categories": categories,
                "published_date": db_paper.published_date.isoformat(),
                "created_at": datetime.now(UTC).isoformat(),
            }

            self.opensearch_client.index(
                index=index_name,
                id=chunk.chunk_id,
                body=doc,
                refresh=False,
            )
            stats["chunks_indexed"] += 1

        # Single refresh after the batch so the upload is immediately searchable
        self.opensearch_client.indices.refresh(index=index_name)
        self.db_session.commit()
        await self.embeddings_client.close()
        logger.info(f"Finished indexing uploaded paper {arxiv_id} with {len(chunks)} chunks.")
        return stats

    async def _process_single_paper(self, paper: PaperMetadata, stats: dict[str, Any]) -> None:
        """Execute single-paper fetch -> parse -> chunk -> embed -> index pipeline."""
        logger.info(f"Ingesting paper: {paper.paper_id} - '{paper.title}'")

        # 1. Check if paper already processed in SoR Postgres
        existing_paper = self.db_session.query(Paper).filter(Paper.arxiv_id == paper.paper_id).first()
        if existing_paper and existing_paper.pdf_processed:
            logger.info(f"Paper {paper.paper_id} already fully parsed and stored. Skipping Ingestion.")
            return

        # 2. Download PDF
        pdf_path = await self.source.download_pdf(paper, self.cache_dir)

        # 3. Parse PDF layout via Docling
        parsed_doc: ParsedDocument | None = None
        try:
            parsed_doc = self.parser.parse(pdf_path)
            stats["parsed"] += 1
        except Exception as e:
            logger.error(f"Docling parsing failed for PDF {pdf_path}: {e}")
            # If docling fails, we store basic arXiv metadata anyway, but set pdf_processed=False
            pass

        # 4. Save/Update Paper metadata in Postgres System of Record
        if not existing_paper:
            db_paper = Paper(
                arxiv_id=paper.paper_id,
                title=paper.title,
                authors=paper.authors,
                abstract=paper.abstract,
                published_date=paper.published_date,
                categories=paper.categories,
                pdf_url=paper.pdf_url,
                raw_text=parsed_doc.raw_text if parsed_doc else None,
                pdf_processed=bool(parsed_doc),
            )
            self.db_session.add(db_paper)
            self.db_session.commit()
            self.db_session.refresh(db_paper)
            existing_paper = db_paper
        else:
            if parsed_doc:
                existing_paper.raw_text = parsed_doc.raw_text
                existing_paper.pdf_processed = True
                existing_paper.updated_at = datetime.now(UTC)
                self.db_session.commit()

        if not parsed_doc:
            logger.warning(f"Aborting chunk/indexing for {paper.paper_id} due to parsing failure.")
            return

        # 5. Chunk layout structure
        chunks = self.chunker.chunk_document(parsed_doc, str(existing_paper.id), paper.paper_id)
        stats["chunks_created"] += len(chunks)

        # Generate layout summaries for tables/figures before embedding
        from src.services.llm_adapter import call_reasoning_llm

        for chunk in chunks:
            if chunk.chunk_type in ("table", "figure", "picture", "equation"):
                try:
                    summary_prompt = (
                        f"You are a scientific layout visual interpreter.\n"
                        f"Summarize this extracted {chunk.chunk_type} layout element and explain its "
                        f"key insights or data points:\n\n"
                        f"{chunk.text[:2000]}"
                    )
                    summary = await call_reasoning_llm(
                        messages=[{"role": "user", "content": summary_prompt}], temperature=0.2, max_tokens=256
                    )
                    chunk.text = f"[Visual Layout Summary: {summary.strip()}]\n\n{chunk.text}"
                except Exception as ex:
                    logger.warning(f"Failed to generate layout summary for {chunk.chunk_id}: {ex}")

        # Delete existing chunks in Postgres to maintain idempotency
        self.db_session.query(Chunk).filter(Chunk.paper_id == existing_paper.id).delete()
        self.db_session.commit()

        # 6. Generate Jina v4 embeddings
        chunk_texts = [c.text for c in chunks]
        embeddings = await self.embeddings_client.embed_passages(chunk_texts)

        # 7. Write to PostgreSQL and index in OpenSearch
        index_name = self.settings.opensearch.chunk_index_name

        for idx, chunk in enumerate(chunks):
            # Save Chunk in PostgreSQL
            db_chunk = Chunk(
                chunk_id=chunk.chunk_id,
                paper_id=existing_paper.id,
                arxiv_id=chunk.arxiv_id,
                section_title=chunk.section_title,
                chunk_type=chunk.chunk_type,
                text=chunk.text,
                page_number=chunk.page_number,
            )
            self.db_session.add(db_chunk)

            # Index in OpenSearch
            doc = {
                "chunk_id": chunk.chunk_id,
                "arxiv_id": chunk.arxiv_id,
                "paper_id": str(existing_paper.id),
                "section_title": chunk.section_title,
                "chunk_type": chunk.chunk_type,
                "text": chunk.text,
                "page_number": chunk.page_number,
                "embedding": embeddings[idx],
                "title": paper.title,
                "authors": paper.authors,
                "abstract": paper.abstract,
                "categories": paper.categories,
                "published_date": paper.published_date.isoformat(),
                "created_at": datetime.now(UTC).isoformat(),
            }

            self.opensearch_client.index(
                index=index_name,
                id=chunk.chunk_id,
                body=doc,
                refresh=False,  # Refreshed once per paper below — per-chunk refresh kills throughput
            )
            stats["chunks_indexed"] += 1

        self.opensearch_client.indices.refresh(index=index_name)
        self.db_session.commit()
        logger.info(f"Finished indexing paper {paper.paper_id} with {len(chunks)} chunks.")
