"""Corpus — Citation-tagged Context Builder.

Assembles reranked chunks into a citation-tagged context block that preserves
provenance metadata through to the prompt. Each chunk is numbered [1], [2], ...
and the full citation metadata is returned alongside the formatted context.

This is the bridge between retrieval and generation — it's what makes
"every claim cited to a specific source" actually work.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Tuple

from src.retrieval.hybrid_search import RetrievedChunk

logger = logging.getLogger(__name__)


@dataclass
class CitationMeta:
    """Full citation metadata for a single source chunk."""

    citation_id: int
    chunk_id: str
    paper_title: str
    authors: List[str]
    arxiv_id: str
    arxiv_url: str
    pdf_url: str
    section: str
    chunk_type: str
    snippet: str  # First ~200 chars of the chunk text


@dataclass
class CitationContext:
    """The assembled context string + citation metadata list."""

    context_str: str
    citations: List[CitationMeta]
    chunk_ids_in_context: List[str] = field(default_factory=list)


def build_citation_context(
    chunks: List[RetrievedChunk],
    max_chunks: int = 8,
    snippet_length: int = 200,
) -> CitationContext:
    """Build a numbered, citation-tagged context block from retrieved chunks.

    Returns a CitationContext containing:
    - context_str: formatted text block with [1], [2], ... labels for the LLM
    - citations: full metadata list for resolving citations in the API response
    - chunk_ids_in_context: list of chunk_ids actually included (for validation)
    """
    if not chunks:
        return CitationContext(
            context_str="No relevant sources found.",
            citations=[],
            chunk_ids_in_context=[],
        )

    # Deduplicate by chunk_id, preserving order
    seen = set()
    unique_chunks = []
    for chunk in chunks:
        if chunk.chunk_id not in seen:
            seen.add(chunk.chunk_id)
            unique_chunks.append(chunk)

    # Limit to max_chunks
    selected = unique_chunks[:max_chunks]

    context_parts = []
    citation_metas = []
    chunk_ids = []

    for idx, chunk in enumerate(selected, start=1):
        # Build the citation-tagged context line
        label = f"[{idx}]"
        section = chunk.section_title or "Unknown Section"
        chunk_type = chunk.chunk_type or "body"
        arxiv_id = chunk.arxiv_id or "unknown"

        context_block = (
            f"--- Source {label} ---\n"
            f"Paper: {chunk.paper_title or 'Unknown'} (arXiv:{arxiv_id})\n"
            f"Section: {section} | Type: {chunk_type}\n"
            f"Content:\n{chunk.text}\n"
            f"--- End Source {label} ---\n"
        )
        context_parts.append(context_block)

        # Build citation metadata
        snippet = chunk.text[:snippet_length].strip()
        if len(chunk.text) > snippet_length:
            snippet += "..."

        authors = chunk.authors if hasattr(chunk, "authors") and chunk.authors else []

        citation_metas.append(
            CitationMeta(
                citation_id=idx,
                chunk_id=chunk.chunk_id,
                paper_title=chunk.paper_title or "Unknown",
                authors=authors,
                arxiv_id=arxiv_id,
                arxiv_url=f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id != "unknown" else "",
                pdf_url=f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id != "unknown" else "",
                section=section,
                chunk_type=chunk_type,
                snippet=snippet,
            )
        )
        chunk_ids.append(chunk.chunk_id)

    context_str = "\n".join(context_parts)

    logger.info(
        f"Built citation context: {len(selected)} sources from {len(chunks)} candidates"
    )

    return CitationContext(
        context_str=context_str,
        citations=citation_metas,
        chunk_ids_in_context=chunk_ids,
    )
