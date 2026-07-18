from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.db.postgres import Base


class Paper(Base):
    """System of Record (SoR) model representing an ingested research paper."""

    __tablename__ = "papers"
    __table_args__ = (
        Index("ix_papers_published_date", "published_date"),
        Index("ix_papers_pdf_processed", "pdf_processed"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    arxiv_id = Column(String, unique=True, nullable=False, index=True)
    title = Column(String, nullable=False)
    authors = Column(JSON, nullable=False)  # List of author names
    abstract = Column(Text, nullable=False)
    published_date = Column(DateTime, nullable=False)
    categories = Column(JSON, nullable=False)  # List of categories
    pdf_url = Column(String, nullable=False)

    # Full body extracted content details
    raw_text = Column(Text, nullable=True)
    pdf_processed = Column(Boolean, default=False, nullable=False)

    # Relationships
    chunks = relationship("Chunk", back_populates="paper", cascade="all, delete-orphan")

    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class Chunk(Base):
    """System of Record model representing a single structure-aware segment of text from a paper."""

    __tablename__ = "chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chunk_id = Column(String, unique=True, nullable=False, index=True)  # stable hash identifier
    paper_id = Column(UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    arxiv_id = Column(String, nullable=False, index=True)

    section_title = Column(String, nullable=False)
    chunk_type = Column(String, nullable=False)  # body, table, figure-caption, equation
    text = Column(Text, nullable=False)

    # Relationships
    paper = relationship("Paper", back_populates="chunks")

    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)


class Feedback(Base):
    """Model representing user thumbs up/down feedback."""

    __tablename__ = "feedbacks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query_id = Column(String, nullable=False, index=True)
    rating = Column(String, nullable=False)  # up or down
    correction = Column(Text, nullable=True)
    trace_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)


class MemoryNode(Base):
    """Model representing a node in the user profile memory graph."""

    __tablename__ = "memory_nodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(String, nullable=False, index=True)
    label = Column(String, nullable=False)  # e.g., "User", "Topic", "Preference"
    properties = Column(JSON, nullable=False)  # e.g., {"topic": "Pretraining Poisoning", "score": 0.9}
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)


class MemoryEdge(Base):
    """Model representing a directed relationship in the user profile memory graph."""

    __tablename__ = "memory_edges"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(
        UUID(as_uuid=True), ForeignKey("memory_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_id = Column(
        UUID(as_uuid=True), ForeignKey("memory_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relation = Column(String, nullable=False)  # e.g., "INTERESTED_IN", "PREFERS"
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
