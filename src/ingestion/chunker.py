from __future__ import annotations

import hashlib
import logging
import re

from src.config import get_settings
from src.ingestion.pdf_parser import ParsedDocument, ParsedSection

logger = logging.getLogger(__name__)


class IngestedChunk:
    """Represents a text chunk prepared for embedding and database insertion."""

    def __init__(
        self,
        chunk_id: str,
        paper_id: str,
        arxiv_id: str,
        section_title: str,
        chunk_type: str,  # "body", "table", "figure-caption", "equation"
        text: str,
    ):
        self.chunk_id = chunk_id
        self.paper_id = paper_id
        self.arxiv_id = arxiv_id
        self.section_title = section_title
        self.chunk_type = chunk_type
        self.text = text


class StructureAwareChunker:
    """Structure-aware chunker that respects section boundaries and handles tables/equations atomically."""

    def __init__(self):
        self.settings = get_settings()

    def generate_chunk_id(self, paper_id: str, section_title: str, chunk_index: int, text: str) -> str:
        """Create a stable, unique chunk identifier based on a hash of text and metadata."""
        hasher = hashlib.sha256()
        hasher.update(f"{paper_id}_{section_title}_{chunk_index}_{text}".encode())
        return hasher.hexdigest()

    def chunk_document(self, doc: ParsedDocument, paper_id: str, arxiv_id: str) -> list[IngestedChunk]:
        """Convert a ParsedDocument into a flat list of IngestedChunks."""
        chunks: list[IngestedChunk] = []

        # 1. Process Sections (Text Body chunks)
        for sec in doc.sections:
            section_chunks = self._chunk_section(sec, paper_id, arxiv_id)
            chunks.extend(section_chunks)

        # 2. Process Elements (Tables/Equations) as Atomic Chunks
        for idx, el in enumerate(doc.elements):
            chunk_type = el.content_type
            # Keep table or equation fully intact as a single block
            chunk_text = el.content
            if el.caption:
                chunk_text = f"Caption: {el.caption}\n\n{chunk_text}"

            chunks.append(
                IngestedChunk(
                    chunk_id="",  # Will be populated during post-processing
                    paper_id=paper_id,
                    arxiv_id=arxiv_id,
                    section_title=f"Metadata - {chunk_type.capitalize()}",
                    chunk_type=chunk_type,
                    text=chunk_text,
                )
            )

        # Post-process all chunks to assign unique, stable hashes using a global index
        for idx, chunk in enumerate(chunks):
            chunk.chunk_id = self.generate_chunk_id(paper_id, chunk.section_title, idx, chunk.text)

        logger.info(f"Chunked document {arxiv_id} into {len(chunks)} chunks.")
        return chunks

    def _chunk_section(self, section: ParsedSection, paper_id: str, arxiv_id: str) -> list[IngestedChunk]:
        """Split a single section into overlapping body text chunks using sentence boundaries."""
        chunks: list[IngestedChunk] = []
        text = section.text.strip()
        if not text:
            return []

        # Split into sentences using a regex to avoid mid-sentence splitting
        sentence_endings = re.compile(r"(?<=[.!?])\s+")
        sentences = sentence_endings.split(text)

        target_size = self.settings.chunking.chunk_size  # ~500 words/tokens
        overlap = self.settings.chunking.overlap_size  # ~75 words/tokens

        current_sentences: list[str] = []
        current_word_count = 0
        chunk_idx = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            words = sentence.split()
            sentence_word_count = len(words)

            if current_word_count + sentence_word_count > target_size and current_sentences:
                # Flush current chunk
                chunk_text = " ".join(current_sentences)
                chunk_id = self.generate_chunk_id(paper_id, section.title, chunk_idx, chunk_text)
                chunks.append(
                    IngestedChunk(
                        chunk_id=chunk_id,
                        paper_id=paper_id,
                        arxiv_id=arxiv_id,
                        section_title=section.title,
                        chunk_type="body",
                        text=chunk_text,
                    )
                )
                chunk_idx += 1

                # Keep sentences that fit inside overlap window
                overlap_sentences = []
                overlap_words = 0
                for s in reversed(current_sentences):
                    s_words = len(s.split())
                    if overlap_words + s_words <= overlap:
                        overlap_sentences.insert(0, s)
                        overlap_words += s_words
                    else:
                        break

                current_sentences = overlap_sentences
                current_word_count = overlap_words

            current_sentences.append(sentence)
            current_word_count += sentence_word_count

        # Flush final remaining sentences
        if current_sentences:
            chunk_text = " ".join(current_sentences)
            chunk_id = self.generate_chunk_id(paper_id, section.title, chunk_idx, chunk_text)
            chunks.append(
                IngestedChunk(
                    chunk_id=chunk_id,
                    paper_id=paper_id,
                    arxiv_id=arxiv_id,
                    section_title=section.title,
                    chunk_type="body",
                    text=chunk_text,
                )
            )

        return chunks
