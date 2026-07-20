"""Corpus — paper administration (deletion with full fan-out).

Deleting a paper must reach every store it touches. Postgres FK cascades
handle chunks and collection links, but three things have no cascade and
must be cleaned explicitly: the OpenSearch chunk documents (separate store),
the concept-graph rows keyed by the arxiv_id string (no FK), and the cached
PDF file on disk. Missing any of these leaves orphaned data that resurfaces
in search, the galaxy, or the PDF viewer.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def delete_paper_everywhere(db, opensearch, arxiv_id: str) -> dict[str, Any]:
    """Remove a paper and all its derived data across every store.

    Returns a per-store summary. Raises LookupError if the paper does not exist.
    Best-effort on the non-Postgres stores: a failure to reach OpenSearch or
    delete the PDF is logged and reported, not fatal — the source-of-truth row
    is still removed so the paper disappears from the app.
    """
    from src.config import get_settings
    from src.models.paper import ConceptEdge, ConceptMention, Paper

    paper = db.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
    if paper is None:
        raise LookupError(f"Paper {arxiv_id} not found.")

    summary: dict[str, Any] = {"arxiv_id": arxiv_id, "opensearch_deleted": 0, "pdf_deleted": False, "errors": []}

    # 1. OpenSearch chunk documents (separate store — no FK cascade).
    try:
        index_name = get_settings().opensearch.chunk_index_name
        resp = opensearch.delete_by_query(
            index=index_name,
            body={"query": {"term": {"arxiv_id": arxiv_id}}},
            refresh=True,
            ignore=[404],
        )
        summary["opensearch_deleted"] = int(resp.get("deleted", 0)) if isinstance(resp, dict) else 0
    except Exception as e:
        logger.error(f"delete_paper: OpenSearch cleanup failed for {arxiv_id}: {e}")
        summary["errors"].append(f"opensearch: {e}")

    # 2. Concept-graph rows keyed by the arxiv_id string (no FK to cascade).
    try:
        edges = db.query(ConceptEdge).filter(ConceptEdge.arxiv_id == arxiv_id).delete(synchronize_session=False)
        mentions = (
            db.query(ConceptMention).filter(ConceptMention.arxiv_id == arxiv_id).delete(synchronize_session=False)
        )
        summary["concept_edges_deleted"] = int(edges or 0)
        summary["concept_mentions_deleted"] = int(mentions or 0)
    except Exception as e:
        logger.error(f"delete_paper: concept-graph cleanup failed for {arxiv_id}: {e}")
        summary["errors"].append(f"concepts: {e}")

    # 3. Cached PDF on disk.
    try:
        safe_id = arxiv_id.replace("/", "_")
        pdf_path = Path(get_settings().arxiv.pdf_cache_dir) / f"{safe_id}.pdf"
        if pdf_path.exists():
            pdf_path.unlink()
            summary["pdf_deleted"] = True
    except Exception as e:
        logger.error(f"delete_paper: PDF cleanup failed for {arxiv_id}: {e}")
        summary["errors"].append(f"pdf: {e}")

    # 4. Postgres source of truth (cascades to chunks + collection links via FK).
    db.delete(paper)
    db.commit()

    logger.info(f"delete_paper: removed {arxiv_id} — {summary}")
    return summary
