"""Corpus — idempotent startup migrations.

`Base.metadata.create_all` creates new tables but never alters existing ones.
Every statement here must be safe to run on every boot (IF NOT EXISTS etc.).
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

MIGRATIONS: list[str] = [
    # Phase 1: page-accurate citations
    "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS page_number INTEGER",
    # Phase 2: reading tracker
    "ALTER TABLE papers ADD COLUMN IF NOT EXISTS reading_status VARCHAR NOT NULL DEFAULT 'unread'",
    "ALTER TABLE papers ADD COLUMN IF NOT EXISTS notes TEXT",
    # Phase 2: concept-graph checkpointing
    "ALTER TABLE papers ADD COLUMN IF NOT EXISTS concepts_extracted_at TIMESTAMP",
    # Phase 2: chat message idempotency + lookup indexes
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_msgs_session_client
       ON chat_messages(session_id, client_msg_id) WHERE client_msg_id IS NOT NULL""",
    "CREATE INDEX IF NOT EXISTS ix_msgs_session_created ON chat_messages(session_id, created_at)",
]


def run_startup_migrations(engine: Engine) -> None:
    """Apply all idempotent migrations; failures are logged but never fatal per-statement."""
    with engine.begin() as conn:
        for stmt in MIGRATIONS:
            try:
                conn.execute(text(stmt))
            except Exception as e:
                # e.g. index migration before its table exists on a fresh DB —
                # create_all runs first, so this only fires on genuine issues.
                logger.warning(f"Startup migration skipped ({e}): {stmt[:80]}")
    logger.info("Startup migrations applied.")
