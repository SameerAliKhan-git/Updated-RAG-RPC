from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

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

    def __init__(self, sections: List[ParsedSection], elements: List[ParsedElement], raw_text: str):
        self.sections = sections
        self.elements = elements
        self.raw_text = raw_text


class DoclingParserService:
    """Layout-aware PDF parsing wrapper powered by IBM Docling."""

    def __init__(self):
        self.settings = get_settings()
        self._converter: Optional[DocumentConverter] = None
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

        sections: List[ParsedSection] = []
        elements: List[ParsedElement] = []

        # Current section tracker
        curr_title = "Introduction"
        curr_text_lines: List[str] = []

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
