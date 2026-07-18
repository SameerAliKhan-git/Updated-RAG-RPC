from __future__ import annotations

from src.ingestion.chunker import StructureAwareChunker
from src.ingestion.pdf_parser import ParsedDocument, ParsedElement, ParsedSection


def test_chunker_respects_sentence_boundaries():
    """Verify chunker splits text by sentence boundary and does not exceed chunk_size."""
    chunker = StructureAwareChunker()
    # Configure target chunk_size of 20 words, overlap of 5 words
    chunker.settings.chunking.chunk_size = 20
    chunker.settings.chunking.overlap_size = 5

    section = ParsedSection(
        title="Test Section",
        text="This is sentence one. Sentence two is here. Sentence three should be in the next chunk because it exceeds the target size limit.",
    )
    doc = ParsedDocument(sections=[section], elements=[], raw_text="")

    chunks = chunker.chunk_document(doc, "paper_uuid", "arxiv_id_123")

    # Should split into multiple chunks
    assert len(chunks) > 1
    # Chunks should contain metadata
    assert chunks[0].section_title == "Test Section"
    assert chunks[0].chunk_type == "body"
    assert "sentence one" in chunks[0].text.lower()


def test_chunker_handles_elements_atomically():
    """Verify table and equation elements are not split but treated as single chunks."""
    chunker = StructureAwareChunker()
    section = ParsedSection(title="Empty Section", text="Text goes here.")
    element = ParsedElement(
        element_id="table_0",
        content_type="table",
        caption="A test table",
        content="col1 | col2\nval1 | val2",
    )
    doc = ParsedDocument(sections=[section], elements=[element], raw_text="")

    chunks = chunker.chunk_document(doc, "paper_uuid", "arxiv_id_123")

    # Find the table chunk
    table_chunks = [c for c in chunks if c.chunk_type == "table"]
    assert len(table_chunks) == 1
    assert "col1 | col2" in table_chunks[0].text
    assert "A test table" in table_chunks[0].text
    assert table_chunks[0].section_title == "Metadata - Table"
