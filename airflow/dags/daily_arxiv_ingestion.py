from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

# Add project root to path for imports to resolve within Airflow containers
sys.path.insert(0, "/opt/airflow")


def setup_environment_task():
    """Create PostgreSQL tables and initialize OpenSearch index configurations."""
    import structlog
    from src.config import get_settings
    from src.db.opensearch import create_opensearch_client, setup_opensearch_indices
    from src.db.postgres import Base, create_engine_and_session

    logger = structlog.get_logger(__name__)
    settings = get_settings()

    logger.info("ingestion.setup_environment.start")

    # 1. Create PostgreSQL tables
    from src.models.paper import Paper, Chunk
    engine, _ = create_engine_and_session(settings.postgres.database_url)
    Base.metadata.create_all(bind=engine)
    logger.info("ingestion.postgres.tables_initialized")

    # 2. Setup OpenSearch indices
    os_client = create_opensearch_client(settings.opensearch.host)
    setup_opensearch_indices(os_client)
    logger.info("ingestion.opensearch.indices_initialized")


def run_ingestion_task():
    """Execute the core ingestion pipeline."""
    import structlog
    from src.config import get_settings
    from src.db.opensearch import create_opensearch_client
    from src.db.postgres import create_engine_and_session
    from src.ingestion.orchestrator import IngestionOrchestrator

    logger = structlog.get_logger(__name__)
    settings = get_settings()

    logger.info("ingestion.orchestrator.start")

    # Initialize connections
    _, session_factory = create_engine_and_session(settings.postgres.database_url)
    os_client = create_opensearch_client(settings.opensearch.host)

    with session_factory() as session:
        orchestrator = IngestionOrchestrator(session, os_client)
        # Fetch search_category from settings, default cs.AI
        category = settings.arxiv.search_category
        limit = settings.arxiv.max_results  # Default 50; configure via ARXIV__MAX_RESULTS
        logger.info("ingestion.pipeline.trigger", category=category, limit=limit)

        loop = asyncio.get_event_loop()
        stats = loop.run_until_complete(orchestrator.ingest_papers(category=category, limit=limit))

    logger.info("ingestion.orchestrator.completed", stats=stats)


def verify_and_report_task():
    """Verify consistency by comparing Postgres and OpenSearch document counts."""
    import structlog
    from src.config import get_settings
    from src.db.opensearch import create_opensearch_client
    from src.db.postgres import create_engine_and_session
    from src.models.paper import Chunk, Paper

    logger = structlog.get_logger(__name__)
    settings = get_settings()

    _, session_factory = create_engine_and_session(settings.postgres.database_url)
    os_client = create_opensearch_client(settings.opensearch.host)

    # Postgres Counts
    with session_factory() as session:
        paper_count = session.query(Paper).count()
        chunk_count = session.query(Chunk).count()

    # OpenSearch Chunks Count
    index_name = settings.opensearch.chunk_index_name
    os_count = 0
    try:
        resp = os_client.count(index=index_name)
        os_count = resp.get("count", 0)
    except Exception as e:
        logger.error("opensearch.count.failed", index=index_name, error=str(e))

    logger.info(
        "ingestion.verify_report",
        postgres_papers=paper_count,
        postgres_chunks=chunk_count,
        opensearch_chunks=os_count,
        match=bool(chunk_count == os_count),
    )


# --- Airflow DAG Definition ---

default_args = {
    "owner": "corpus",
    "depends_on_past": False,
    "start_date": datetime(2026, 1, 1),
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    "daily_arxiv_ingestion",
    default_args=default_args,
    description="Daily ingestion pipeline: fetch papers, parse layout, chunk, embed and index.",
    schedule="0 6 * * 1-5",  # Mon-Fri at 6:00 AM UTC
    catchup=False,
    max_active_runs=1,
    tags=["corpus", "ingestion", "arxiv", "docling"],
) as dag:
    setup_env = PythonOperator(
        task_id="setup_environment",
        python_callable=setup_environment_task,
    )

    ingest_papers = PythonOperator(
        task_id="fetch_and_parse_chunk_index",
        python_callable=run_ingestion_task,
    )

    verify_report = PythonOperator(
        task_id="generate_daily_report",
        python_callable=verify_and_report_task,
    )

    cleanup = BashOperator(
        task_id="cleanup_temp_files",
        bash_command='echo "Cleaning up temporary downloads..." && rm -rf /tmp/*.pdf',
    )

    setup_env >> ingest_papers >> verify_report >> cleanup
