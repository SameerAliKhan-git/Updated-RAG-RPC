from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path


class PaperMetadata(ABC):
    """Abstract model representing fetched paper metadata."""

    @property
    @abstractmethod
    def paper_id(self) -> str:
        """Unique ID of the paper from the source."""
        pass

    @property
    @abstractmethod
    def title(self) -> str:
        """Paper title."""
        pass

    @property
    @abstractmethod
    def authors(self) -> list[str]:
        """Authors list."""
        pass

    @property
    @abstractmethod
    def abstract(self) -> str:
        """Abstract summary."""
        pass

    @property
    @abstractmethod
    def published_date(self) -> datetime:
        """Publication date."""
        pass

    @property
    @abstractmethod
    def categories(self) -> list[str]:
        """Associated subject categories."""
        pass

    @property
    @abstractmethod
    def pdf_url(self) -> str:
        """PDF file URL."""
        pass


class PaperSource(ABC):
    """Abstract repository representing an external paper source."""

    @abstractmethod
    async def fetch_recent_papers(
        self,
        category: str,
        limit: int = 50,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[PaperMetadata]:
        """Fetch metadata for recent papers from the source."""
        pass

    @abstractmethod
    async def fetch_by_id(self, paper_id: str) -> PaperMetadata | None:
        """Fetch a single paper by its source-specific ID (e.g. arXiv ID)."""
        pass

    @abstractmethod
    async def download_pdf(self, paper: PaperMetadata, target_dir: Path) -> Path:
        """Download paper PDF to target directory and return file path."""
        pass

    async def close(self) -> None:  # noqa: B027 — optional hook, not all sources hold resources
        """Clean up any resources held by the source."""
        pass
