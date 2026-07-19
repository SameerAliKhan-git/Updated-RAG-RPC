"""Corpus — Re-embed and re-index all chunks with the local embedding model.

Run after switching embedding backends (e.g. Jina → bge-m3): stored vectors
must come from the same model that embeds queries, or KNN search is meaningless.

Papers and chunks in Postgres are untouched — only the OpenSearch chunk index
is dropped, recreated, and repopulated with fresh embeddings.

Usage:
    uv run python -m src.run_reindex
    # One-off GPU-accelerated run (stop Ollama models first to free VRAM):
    $env:EMBEDDING__DEVICE="cuda"; uv run python -m src.run_reindex
"""

from __future__ import annotations

import asyncio
import logging
import sys

from opensearchpy import helpers as os_helpers

from src.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("run_reindex")

BATCH_SIZE = 32


async def reindex() -> int:
    settings = get_settings()

    from src.db.opensearch import create_opensearch_client, setup_opensearch_indices
    from src.db.postgres import create_engine_and_session
    from src.models.paper import Chunk, Paper
    from src.services.embedding_client import create_embedding_client

    engine, session_factory = create_engine_and_session(settings.postgres.database_url)
    db = session_factory()
    os_client = create_opensearch_client(settings.opensearch.host)
    embedder = create_embedding_client()
    index_name = settings.opensearch.chunk_index_name

    try:
        total_chunks = db.query(Chunk).count()
        if total_chunks == 0:
            logger.warning("No chunks in Postgres — nothing to reindex.")
            return 0
        logger.info(f"Reindexing {total_chunks} chunks into '{index_name}' "
                    f"with {settings.embedding.model_name} on {settings.embedding.device}...")

        # Drop and recreate the index with the existing mapping
        if os_client.indices.exists(index=index_name):
            os_client.indices.delete(index=index_name)
            logger.info(f"Deleted index '{index_name}'.")
        setup_opensearch_indices(os_client)

        indexed = 0
        offset = 0
        while True:
            rows = (
                db.query(Chunk, Paper)
                .join(Paper, Chunk.paper_id == Paper.id)
                .order_by(Chunk.created_at)
                .offset(offset)
                .limit(BATCH_SIZE)
                .all()
            )
            if not rows:
                break
            offset += len(rows)

            texts = [chunk.text for chunk, _ in rows]
            embeddings = await embedder.embed_passages(texts)

            actions = []
            for (chunk, paper), embedding in zip(rows, embeddings, strict=True):
                actions.append(
                    {
                        "_index": index_name,
                        "_id": chunk.chunk_id,
                        "_source": {
                            "chunk_id": chunk.chunk_id,
                            "arxiv_id": chunk.arxiv_id,
                            "paper_id": str(chunk.paper_id),
                            "section_title": chunk.section_title,
                            "chunk_type": chunk.chunk_type,
                            "text": chunk.text,
                            "page_number": chunk.page_number,
                            "embedding": embedding,
                            "title": paper.title,
                            "authors": paper.authors or [],
                            "abstract": paper.abstract or "",
                            "categories": paper.categories or [],
                            "published_date": paper.published_date.isoformat() if paper.published_date else None,
                            "created_at": chunk.created_at.isoformat() if chunk.created_at else None,
                        },
                    }
                )

            os_helpers.bulk(os_client, actions, refresh=False)
            indexed += len(actions)
            logger.info(f"Indexed {indexed}/{total_chunks} chunks...")

        os_client.indices.refresh(index=index_name)

        # Parity check: Postgres chunk count must equal OpenSearch doc count
        os_count = os_client.count(index=index_name)["count"]
        if os_count == total_chunks:
            logger.info(f"✓ Parity check passed: {os_count} docs in OpenSearch == {total_chunks} chunks in Postgres.")
        else:
            logger.error(f"✗ Parity MISMATCH: OpenSearch has {os_count} docs, Postgres has {total_chunks} chunks.")
            return 1

        # Stale semantic-cache answers reference old retrieval results — flush them
        await _flush_semantic_cache(settings)
        return 0
    finally:
        await embedder.close()
        db.close()
        os_client.close()
        engine.dispose()


async def _flush_semantic_cache(settings) -> None:
    try:
        import redis.asyncio as aioredis

        redis = aioredis.from_url(settings.redis.url)
        deleted = 0
        async for key in redis.scan_iter(match="corpus:semcache:*", count=100):
            await redis.delete(key)
            deleted += 1
        await redis.aclose()
        logger.info(f"Flushed {deleted} semantic cache entries.")
    except Exception as e:
        logger.warning(f"Semantic cache flush skipped (Redis unavailable?): {e}")


if __name__ == "__main__":
    sys.exit(asyncio.run(reindex()))
