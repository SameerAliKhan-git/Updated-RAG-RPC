from __future__ import annotations

import logging
from pathlib import Path

import pypdfium2 as pdfium
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

from src.config import get_settings

logger = logging.getLogger(__name__)


class ParsedSection:
    """Dataclass representing extracted document section."""

    def __init__(self, title: str, text: str, level: int = 1):
        self.title = title
        self.text = text
        self.level = level


class ParsedElement:
    """Dataclass representing tables, figures, or equations."""

    def __init__(self, element_id: str, content_type: str, caption: str, content: str):
        self.element_id = element_id
        self.content_type = content_type  # "table", "figure", "equation"
        self.caption = caption
        self.content = content


class ParsedDocument:
    """Aggregated parsed result wrapper."""

    def __init__(self, sections: list[ParsedSection], elements: list[ParsedElement], raw_text: str):
        self.sections = sections
        self.elements = elements
        self.raw_text = raw_text


class DoclingParserService:
    """Layout-aware PDF parsing wrapper powered by IBM Docling."""

    def __init__(self):
        self.settings = get_settings()
        self._converter: DocumentConverter | None = None
        self._warmed_up = False

    def _init_converter(self) -> None:
        """Initialize DocumentConverter if not already done."""
        if self._converter is None:
            pipeline_opts = PdfPipelineOptions(
                do_table_structure=self.settings.pdf_parser.do_table_structure,
                do_ocr=False,  # OCR disabled for performance unless forced
            )
            self._converter = DocumentConverter(
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_opts)}
            )

    def _validate_pdf(self, pdf_path: Path) -> int:
        """Validate file size and page count prior to docling converter.

        Returns:
            Number of pages in the PDF.
        """
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file does not exist: {pdf_path}")

        file_size_mb = pdf_path.stat().st_size / (1024 * 1024)
        max_size = self.settings.pdf_parser.max_file_size_mb
        if file_size_mb > max_size:
            raise ValueError(f"PDF size {file_size_mb:.1f}MB exceeds limit of {max_size}MB.")

        # Check page count
        pdf = pdfium.PdfDocument(str(pdf_path))
        try:
            pages = len(pdf)
        finally:
            pdf.close()

        max_pages = self.settings.pdf_parser.max_pages
        if pages > max_pages:
            raise ValueError(f"PDF page count {pages} exceeds allowed limit of {max_pages}.")

        return pages

    def warm_up(self) -> None:
        """Pre-warm docling models on a trivial input to prevent first-call latency spikes."""
        if self._warmed_up:
            return

        logger.info("Pre-warming Docling models...")
        self._init_converter()
        # Warmup complete
        self._warmed_up = True
        logger.info("Docling models successfully pre-warmed.")

    def parse(self, pdf_path: Path) -> ParsedDocument:
        """Convert layout structure of the PDF and build ParsedDocument."""
        self._validate_pdf(pdf_path)
        self.warm_up()

        logger.info(f"Parsing PDF layout via Docling: {pdf_path}")
        result = self._converter.convert(str(pdf_path))
        doc = result.document

        sections: list[ParsedSection] = []
        elements: list[ParsedElement] = []

        # Current section tracker
        curr_title = "Introduction"
        curr_text_lines: list[str] = []

        # Rely on doc.texts to reconstruct chronological narrative text
        for text_item in doc.texts:
            label = getattr(text_item, "label", "")
            if label in ("section_header", "title"):
                # Save previous section
                if curr_text_lines:
                    sections.append(ParsedSection(title=curr_title, text="\n".join(curr_text_lines)))
                    curr_text_lines = []
                curr_title = text_item.text.strip()
            else:
                curr_text_lines.append(text_item.text.strip())

        # Save tail section
        if curr_text_lines:
            sections.append(ParsedSection(title=curr_title, text="\n".join(curr_text_lines)))

        # Rely on tables to extract structured tables
        for tab_idx, table_item in enumerate(doc.tables):
            caption = ""
            if hasattr(table_item, "caption") and table_item.caption:
                caption = table_item.caption
            elif hasattr(table_item, "captions") and table_item.captions:
                parts = []
                for c in table_item.captions:
                    if isinstance(c, str):
                        parts.append(c)
                    elif hasattr(c, "text") and c.text:
                        parts.append(c.text)
                caption = " ".join(parts)
            # Export table content — try multiple Docling v2 access patterns
            table_markdown = ""
            try:
                # Preferred: use the built-in markdown export
                if hasattr(table_item, "export_to_markdown"):
                    table_markdown = table_item.export_to_markdown(doc)
                elif hasattr(table_item, "data") and table_item.data is not None:
                    td = table_item.data
                    # Docling v2: data.grid is a list of rows, each row a list of cells
                    if hasattr(td, "grid") and td.grid:
                        rows = []
                        for grid_row in td.grid:
                            cells = []
                            for cell in grid_row:
                                cell_text = getattr(cell, "text", str(cell)) if cell else ""
                                cells.append(cell_text)
                            rows.append(" | ".join(cells))
                        table_markdown = "\n".join(rows)
                    # Legacy fallback: data.rows
                    elif hasattr(td, "rows") and td.rows:
                        rows = []
                        for row in td.rows:
                            cells_list = getattr(row, "cells", [])
                            cells = [getattr(c, "text", str(c)) for c in cells_list]
                            rows.append(" | ".join(cells))
                        table_markdown = "\n".join(rows)
            except Exception as tbl_err:
                logger.warning(f"Failed to extract table_{tab_idx} content: {tbl_err}")
                table_markdown = "[table extraction failed]"

            elements.append(
                ParsedElement(
                    element_id=f"table_{tab_idx}",
                    content_type="table",
                    caption=caption,
                    content=table_markdown,
                )
            )

        # Extract figures/pictures (Docling v2 API)
        try:
            for fig_idx, fig_item in enumerate(getattr(doc, "pictures", [])):
                caption = ""
                if hasattr(fig_item, "caption") and fig_item.caption:
                    caption = fig_item.caption if isinstance(fig_item.caption, str) else ""
                elif hasattr(fig_item, "captions") and fig_item.captions:
                    parts = []
                    for c in fig_item.captions:
                        if isinstance(c, str):
                            parts.append(c)
                        elif hasattr(c, "text") and c.text:
                            parts.append(c.text)
                    caption = " ".join(parts)

                fig_text = getattr(fig_item, "text", "") or ""
                content = f"Caption: {caption}" if caption else fig_text or "[figure]"

                elements.append(
                    ParsedElement(
                        element_id=f"figure_{fig_idx}",
                        content_type="figure-caption",
                        caption=caption,
                        content=content,
                    )
                )
        except Exception as fig_err:
            logger.warning(f"Failed to extract figures: {fig_err}")

        # Rely on equations (may not exist in all Docling versions)
        try:
            for eq_idx, eq_item in enumerate(getattr(doc, "equations", [])):
                elements.append(
                    ParsedElement(
                        element_id=f"equation_{eq_idx}",
                        content_type="equation",
                        caption="",
                        content=getattr(eq_item, "text", ""),
                    )
                )
        except Exception as eq_err:
            logger.warning(f"Failed to extract equations: {eq_err}")

        # Raw clean text export fallback
        try:
            raw_text = doc.export_to_text()
        except Exception:
            # Fallback: concatenate section texts
            raw_text = "\n\n".join(s.text for s in sections)

        return ParsedDocument(sections=sections, elements=elements, raw_text=raw_text)

    def extract_metadata(self, pdf_path: Path) -> dict:
        """Extract title, authors, and abstract from a PDF using layout analysis.

        Uses the Docling converter's structural labels to identify:
        - Title: first element labelled 'title'
        - Authors: text between title and first section_header (heuristic)
        - Abstract: text under the 'Abstract' section header

        Returns:
            dict with keys 'title', 'authors' (list[str]), 'abstract' (str)
        """
        import re as _re

        self._validate_pdf(pdf_path)
        self.warm_up()

        logger.info(f"Extracting metadata from PDF: {pdf_path}")
        result = self._converter.convert(str(pdf_path))
        doc = result.document

        title = ""
        authors: list[str] = []
        abstract = ""

        # Walk through text items to find title, authors, and abstract
        found_title = False
        collecting_authors = False
        collecting_abstract = False

        for text_item in doc.texts:
            label = getattr(text_item, "label", "")
            text = text_item.text.strip() if text_item.text else ""

            if not text:
                continue

            # Detect the title (first 'title' label)
            if label == "title" and not found_title:
                title = text
                found_title = True
                collecting_authors = True
                continue

            # After the title, collect author-like text until we hit a section header
            if collecting_authors:
                if label == "section_header":
                    collecting_authors = False
                    # Check if this section is the abstract
                    if text.lower().strip().startswith("abstract"):
                        collecting_abstract = True
                    continue

                # Heuristic: author lines are typically short, comma/and-separated names
                # Skip lines that look like affiliations (contain @, university, dept, etc.)
                line_lower = text.lower()
                is_affiliation = any(
                    kw in line_lower
                    for kw in [
                        "@",
                        "university",
                        "department",
                        "institute",
                        "laboratory",
                        "school of",
                        "faculty",
                        "college",
                        "research center",
                        "inc.",
                        "corp.",
                        "ltd.",
                    ]
                )
                if not is_affiliation and len(text) < 300:
                    # Split on commas, semicolons, and 'and' to get individual names
                    raw_names = _re.split(r"[,;]\s*|\band\b", text)
                    for name in raw_names:
                        name = name.strip()
                        # Filter: valid author names are 2-60 chars, contain letters
                        if (
                            name
                            and 2 <= len(name) <= 60
                            and _re.search(r"[a-zA-Z]", name)
                            and not _re.match(r"^[\d∗†‡§¶\*]+$", name)
                        ):
                            authors.append(name)
                continue

            # Collect abstract text
            if collecting_abstract:
                if label == "section_header":
                    # Reached the next section, stop collecting
                    collecting_abstract = False
                    continue
                abstract += (" " if abstract else "") + text
                continue

            # If we haven't found the abstract yet, check for it
            if label == "section_header" and text.lower().strip().startswith("abstract"):
                collecting_abstract = True

        # Fallback: if no title found from labels, use the first text line
        if not title and doc.texts:
            title = doc.texts[0].text.strip()

        # Deduplicate authors while preserving order
        seen = set()
        unique_authors = []
        for a in authors:
            if a.lower() not in seen:
                seen.add(a.lower())
                unique_authors.append(a)

        logger.info(
            f"Extracted metadata — title: '{title[:60]}...', "
            f"authors: {len(unique_authors)}, abstract: {len(abstract)} chars"
        )

        return {
            "title": title,
            "authors": unique_authors,
            "abstract": abstract[:2000],  # Cap abstract length
        }
