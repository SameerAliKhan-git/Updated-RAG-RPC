"""Corpus — OpenSearch client factory."""

from __future__ import annotations

from opensearchpy import OpenSearch


def create_opensearch_client(host: str) -> OpenSearch:
    """Create an OpenSearch client with connection pooling.

    Args:
        host: OpenSearch host URL (e.g. http://localhost:9200).

    Returns:
        Configured OpenSearch client instance.
    """
    # Parse host/port from URL
    clean_host = host.replace("http://", "").replace("https://", "")
    hostname, _, port_str = clean_host.partition(":")
    port = int(port_str) if port_str else 9200

    return OpenSearch(
        hosts=[{"host": hostname, "port": port}],
        http_compress=True,
        use_ssl=False,
        verify_certs=False,
        ssl_show_warn=False,
        timeout=30,
        max_retries=3,
        retry_on_timeout=True,
    )


def setup_opensearch_indices(client: OpenSearch) -> None:
    """Initialize index templates, mappings, and post-search pipelines.

    Args:
        client: Connected OpenSearch client instance.
    """
    import structlog

    from src.config import get_settings
    from src.db.opensearch_mapping import OPENSEARCH_CHUNKS_MAPPING, OPENSEARCH_RRF_PIPELINE

    logger = structlog.get_logger(__name__)
    settings = get_settings()

    # 1. Register RRF pipeline
    pipeline_name = settings.opensearch.rrf_pipeline_name
    try:
        client.http.put(f"/_search/pipeline/{pipeline_name}", body=OPENSEARCH_RRF_PIPELINE)
        logger.info("opensearch.rrf_pipeline.registered", pipeline=pipeline_name)
    except Exception as e:
        logger.error("opensearch.rrf_pipeline.failed", pipeline=pipeline_name, error=str(e))
        raise

    # 2. Setup Index
    index_name = settings.opensearch.chunk_index_name
    try:
        if not client.indices.exists(index=index_name):
            client.indices.create(index=index_name, body=OPENSEARCH_CHUNKS_MAPPING)
            logger.info("opensearch.index.created", index=index_name)
        else:
            logger.info("opensearch.index.exists", index=index_name)
    except Exception as e:
        logger.error("opensearch.index.failed", index=index_name, error=str(e))
        raise
