"""Direct ingestion runner — bypasses Airflow scheduler for faster iteration."""

import asyncio
import sys
import structlog

# Add project root to path
from pathlib import Path
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)
sys.path.insert(0, "/opt/airflow")
sys.path.insert(0, "/app")

from src.config import get_settings
from src.db.opensearch import create_opensearch_client, setup_opensearch_indices
from src.db.postgres import Base, create_engine_and_session
from src.ingestion.orchestrator import IngestionOrchestrator
from src.models.paper import Paper, Chunk

logger = structlog.get_logger(__name__)


async def main():
    settings = get_settings()

    # 1. Setup DB tables
    engine, session_factory = create_engine_and_session(settings.postgres.database_url)
    Base.metadata.create_all(bind=engine)
    logger.info("postgres.tables.ready")

    # 2. Setup OpenSearch
    os_client = create_opensearch_client(settings.opensearch.host)
    setup_opensearch_indices(os_client)
    logger.info("opensearch.indices.ready")

    # 3. Run ingestion (limit=5)
    with session_factory() as session:
        orchestrator = IngestionOrchestrator(session, os_client)
        category = settings.arxiv.search_category
        limit = 5
        logger.info("ingestion.start", category=category, limit=limit)
        stats = await orchestrator.ingest_papers(category=category, limit=limit)
        logger.info("ingestion.complete", stats=stats)

    # 4. Report
    with session_factory() as session:
        paper_count = session.query(Paper).count()
        chunk_count = session.query(Chunk).count()
        processed = session.query(Paper).filter(Paper.pdf_processed == True).count()
        logger.info("final.counts", papers=paper_count, processed=processed, chunks=chunk_count)

    # OpenSearch count
    try:
        resp = os_client.count(index=settings.opensearch.chunk_index_name)
        os_count = resp.get("count", 0)
        logger.info("opensearch.chunks", count=os_count)
    except Exception as e:
        logger.error("opensearch.count.failed", error=str(e))


if __name__ == "__main__":
    asyncio.run(main())
