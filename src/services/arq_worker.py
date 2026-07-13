"""Corpus — Arq Task Worker.

Background process that runs on-demand single-paper ingestion tasks
triggered by user queries for unindexed papers.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
project_root = str(Path(__file__).resolve().parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.config import get_settings
from src.db.opensearch import create_opensearch_client
from src.db.postgres import create_engine_and_session
from src.ingestion.orchestrator import IngestionOrchestrator

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


async def ingest_single_paper_task(ctx: dict, arxiv_id: str) -> dict:
    """Ingest a single research paper on-demand.

    This runs inside the arq worker process pool.
    """
    logger.info(f"Arq job starting: Ingesting paper {arxiv_id}...")
    settings = get_settings()

    # 1. Setup connections
    engine, session_factory = create_engine_and_session(settings.postgres.database_url)
    os_client = create_opensearch_client(settings.opensearch.host)

    try:
        with session_factory() as session:
            orchestrator = IngestionOrchestrator(session, os_client)
            # Run ingestion pipeline for single paper
            stats = await orchestrator.ingest_papers(category="", limit=1, specific_arxiv_id=arxiv_id)

        logger.info(f"Arq job complete: Ingested paper {arxiv_id}. Stats: {stats}")
        return stats

    except Exception as e:
        logger.error(f"Arq job failed for paper {arxiv_id}: {e}", exc_info=True)
        return {"status": "failed", "error": str(e)}

    finally:
        engine.dispose()


# ─── Arq Worker Configuration ──────────────────────────────────────


class WorkerSettings:
    """Settings required by arq worker startup command."""

    functions = [ingest_single_paper_task]
    redis_settings = None

    # Load settings dynamically on start
    settings = get_settings()
    from arq.connections import RedisSettings as ArqRedisSettings

    redis_settings = ArqRedisSettings(
        host=settings.redis.host,
        port=settings.redis.port,
        password=settings.redis.password or None,
        database=settings.redis.db,
    )
