from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text
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

    # Researcher workflow: reading tracker
    reading_status = Column(String, nullable=False, default="unread")  # unread|to_read|reading|done
    notes = Column(Text, nullable=True)

    # Concept-graph extraction checkpoint (nightly DAG)
    concepts_extracted_at = Column(DateTime, nullable=True)

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
    page_number = Column(Integer, nullable=True)  # 1-based PDF page for citation deep-links

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


class Collection(Base):
    """A named group of papers — the scope unit for notebook-style chat."""

    __tablename__ = "collections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, unique=True, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    papers = relationship("CollectionPaper", back_populates="collection", cascade="all, delete-orphan")


class CollectionPaper(Base):
    """Membership of a paper in a collection (M2M)."""

    __tablename__ = "collection_papers"

    collection_id = Column(
        UUID(as_uuid=True), ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True
    )
    paper_id = Column(UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True)
    added_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    collection = relationship("Collection", back_populates="papers")
    paper = relationship("Paper")


class ChatSessionRecord(Base):
    """Durable UI chat history (the LLM's short-term memory stays in Redis)."""

    __tablename__ = "chat_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String, nullable=False, default="New chat")
    collection_id = Column(
        UUID(as_uuid=True), ForeignKey("collections.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    messages = relationship("ChatMessageRecord", back_populates="session", cascade="all, delete-orphan")


class ChatMessageRecord(Base):
    """A single persisted chat message with its citations and grounding metadata."""

    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(
        UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role = Column(String, nullable=False)  # user | assistant
    content = Column(Text, nullable=False)
    citations = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)  # grounding note, cached flag, etc.
    client_msg_id = Column(String, nullable=True)  # idempotency key for client re-push
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    session = relationship("ChatSessionRecord", back_populates="messages")


class ConceptNode(Base):
    """An extracted research concept (method/dataset/task/metric)."""

    __tablename__ = "concept_nodes"
    __table_args__ = (Index("uq_concept_canonical_type", "canonical_name", "type", unique=True),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)  # surface form as first seen
    canonical_name = Column(String, nullable=False)  # normalized merge key
    type = Column(String, nullable=False)  # method | dataset | task | metric
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)


class ConceptMention(Base):
    """Which papers mention a concept — powers papers_for_concept lookups."""

    __tablename__ = "concept_mentions"

    concept_id = Column(
        UUID(as_uuid=True), ForeignKey("concept_nodes.id", ondelete="CASCADE"), primary_key=True
    )
    arxiv_id = Column(String, primary_key=True)


class ConceptEdge(Base):
    """A typed relation between two concepts, evidenced by one paper."""

    __tablename__ = "concept_edges"
    __table_args__ = (
        Index("uq_concept_edge", "source_id", "target_id", "relation", "arxiv_id", unique=True),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(UUID(as_uuid=True), ForeignKey("concept_nodes.id", ondelete="CASCADE"), nullable=False)
    target_id = Column(UUID(as_uuid=True), ForeignKey("concept_nodes.id", ondelete="CASCADE"), nullable=False)
    relation = Column(String, nullable=False)  # uses | improves_on | evaluated_on | compares_to
    arxiv_id = Column(String, nullable=False)
    confidence = Column(Integer, nullable=False, default=50)  # 0-100
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
