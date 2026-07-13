"""Corpus — PostgreSQL engine and session factory."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

Base = declarative_base()


def create_engine_and_session(database_url: str) -> tuple:
    """Create a SQLAlchemy engine and session factory.

    Returns:
        Tuple of (engine, sessionmaker).
    """
    engine = create_engine(
        database_url,
        pool_size=10,
        max_overflow=20,
        pool_timeout=30,
        pool_recycle=1800,
        pool_pre_ping=True,
        echo=False,
    )
    session_factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    return engine, session_factory
