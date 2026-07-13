from __future__ import annotations

import asyncio
import logging
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote, urlencode

import httpx
from dateutil import parser as date_parser
from src.config import get_settings
from src.ingestion.interfaces import PaperMetadata, PaperSource

logger = logging.getLogger(__name__)


class ArxivPaperMetadata(PaperMetadata):
    """arXiv-specific implementation of PaperMetadata."""

    def __init__(
        self,
        paper_id: str,
        title: str,
        authors: List[str],
        abstract: str,
        published_date: datetime,
        categories: List[str],
        pdf_url: str,
    ):
        self._paper_id = paper_id
        self._title = title
        self._authors = authors
        self._abstract = abstract
        self._published_date = published_date
        self._categories = categories
        self._pdf_url = pdf_url

    @property
    def paper_id(self) -> str:
        return self._paper_id

    @property
    def title(self) -> str:
        return self._title

    @property
    def authors(self) -> List[str]:
        return self._authors

    @property
    def abstract(self) -> str:
        return self._abstract

    @property
    def published_date(self) -> datetime:
        return self._published_date

    @property
    def categories(self) -> List[str]:
        return self._categories

    @property
    def pdf_url(self) -> str:
        return self._pdf_url


class ArxivPaperSource(PaperSource):
    """arXiv API integration client with built-in rate-limiting and robust retries."""

    # Namespaces for parsing Atom feeds
    NAMESPACES = {
        "atom": "http://www.w3.org/2005/Atom",
        "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
    }

    def __init__(self):
        self.settings = get_settings()
        self._last_request_time: Optional[float] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        """Fetch or instantiate a reusable HTTPX client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=float(self.settings.arxiv.timeout_seconds))
        return self._client

    async def _throttle(self) -> None:
        """Throttle requests to conform with arXiv's policy guidelines."""
        async with self._lock:
            if self._last_request_time is not None:
                elapsed = time.monotonic() - self._last_request_time
                delay = self.settings.arxiv.rate_limit_delay
                if elapsed < delay:
                    await asyncio.sleep(delay - elapsed)
            self._last_request_time = time.monotonic()

    async def fetch_recent_papers(
        self,
        category: str,
        limit: int = 50,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> List[PaperMetadata]:
        """Fetch matching paper entries from arXiv."""
        query = f"cat:{category}"
        if from_date or to_date:
            date_from = from_date.strftime("%Y%m%d0000") if from_date else "*"
            date_to = to_date.strftime("%Y%m%d2359") if to_date else "*"
            query += f" AND submittedDate:[{date_from} TO {date_to}]"

        params = {
            "search_query": query,
            "max_results": limit,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }

        # Keep safe characters to prevent double-encoding needed parameters
        safe_chars = ":+[]"
        query_string = urlencode(params, quote_via=quote, safe=safe_chars)
        url = f"{self.settings.arxiv.base_url}?{query_string}"

        logger.info(f"Querying arXiv API: {url}")
        await self._throttle()

        client = await self._get_client()
        resp = await client.get(url)
        resp.raise_for_status()

        return self._parse_feed(resp.text)

    async def fetch_by_id(self, arxiv_id: str) -> Optional[PaperMetadata]:
        """Fetch paper by direct ID list."""
        params = {"id_list": arxiv_id}
        query_string = urlencode(params)
        url = f"{self.settings.arxiv.base_url}?{query_string}"

        await self._throttle()
        client = await self._get_client()
        resp = await client.get(url)
        resp.raise_for_status()

        papers = self._parse_feed(resp.text)
        return papers[0] if papers else None

    def _parse_feed(self, xml_content: str) -> List[PaperMetadata]:
        """Parse XML atom entries."""
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            logger.error("Failed to parse arXiv Atom XML response", exc_info=True)
            return []

        entries = root.findall("atom:entry", self.NAMESPACES)
        papers: List[PaperMetadata] = []

        for entry in entries:
            # ID
            id_elem = entry.find("atom:id", self.NAMESPACES)
            if id_elem is None or not id_elem.text:
                continue
            paper_id = id_elem.text.split("/abs/")[-1].split("/pdf/")[-1].split("v")[0]

            # Title
            title_elem = entry.find("atom:title", self.NAMESPACES)
            title = title_elem.text.strip().replace("\n", " ") if (title_elem is not None and title_elem.text) else ""

            # Abstract
            abstract_elem = entry.find("atom:summary", self.NAMESPACES)
            abstract = abstract_elem.text.strip().replace("\n", " ") if (abstract_elem is not None and abstract_elem.text) else ""

            # Published Date
            pub_elem = entry.find("atom:published", self.NAMESPACES)
            published_date = date_parser.parse(pub_elem.text) if (pub_elem is not None and pub_elem.text) else datetime.now(timezone.utc)

            # Authors
            authors = []
            for author_elem in entry.findall("atom:author", self.NAMESPACES):
                name_elem = author_elem.find("atom:name", self.NAMESPACES)
                if name_elem is not None and name_elem.text:
                    authors.append(name_elem.text.strip())

            # Categories
            categories = []
            for cat_elem in entry.findall("atom:category", self.NAMESPACES):
                term = cat_elem.get("term")
                if term:
                    categories.append(term)

            # PDF URL
            pdf_url = ""
            for link_elem in entry.findall("atom:link", self.NAMESPACES):
                if link_elem.get("title") == "pdf" or link_elem.get("type") == "application/pdf":
                    pdf_url = link_elem.get("href")
                    if pdf_url:
                        if pdf_url.startswith("http://arxiv.org/"):
                            pdf_url = pdf_url.replace("http://arxiv.org/", "https://arxiv.org/")
                        break

            if not pdf_url:
                pdf_url = f"https://arxiv.org/pdf/{paper_id}.pdf"

            papers.append(
                ArxivPaperMetadata(
                    paper_id=paper_id,
                    title=title,
                    authors=authors,
                    abstract=abstract,
                    published_date=published_date,
                    categories=categories,
                    pdf_url=pdf_url,
                )
            )

        return papers

    async def download_pdf(self, paper: PaperMetadata, target_dir: Path) -> Path:
        """Download paper PDF with resilient retry backoff."""
        target_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = target_dir / f"{paper.paper_id.replace('/', '_')}.pdf"

        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            logger.info(f"PDF already cached locally: {pdf_path}")
            return pdf_path

        client = await self._get_client()
        url = paper.pdf_url

        max_attempts = 3
        for attempt in range(max_attempts):
            await self._throttle()
            try:
                logger.info(f"Downloading PDF (attempt {attempt+1}/{max_attempts}) from: {url}")
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    with open(pdf_path, "wb") as f:
                        async for chunk in response.aiter_bytes():
                            f.write(chunk)
                logger.info(f"Successfully downloaded PDF to: {pdf_path}")
                return pdf_path
            except Exception as e:
                logger.warning(f"Failed download attempt {attempt+1} due to error: {e}")
                if pdf_path.exists():
                    pdf_path.unlink()
                if attempt == max_attempts - 1:
                    raise IOError(f"Failed downloading PDF from {url} after {max_attempts} attempts.") from e
                await asyncio.sleep(2.0 * (attempt + 1))

        raise IOError(f"Could not download PDF from: {url}")

    async def close(self) -> None:
        """Teardown reusable clients."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
