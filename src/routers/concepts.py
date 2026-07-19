"""Corpus — concept graph API for the Research Galaxy view."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import func

from src.dependencies import get_db_session
from src.middleware.auth import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["concepts"],
    dependencies=[Depends(verify_api_key)],
)


@router.get("/concepts/graph", summary="Concept graph for the Research Galaxy visualization")
async def concept_graph(
    limit: int = 120,
    db=Depends(get_db_session),
):
    """Nodes (with paper-mention counts) and typed edges of the extracted concept graph."""
    from src.models.paper import ConceptEdge, ConceptMention, ConceptNode

    mention_counts = (
        db.query(ConceptMention.concept_id, func.count(ConceptMention.arxiv_id).label("mentions"))
        .group_by(ConceptMention.concept_id)
        .subquery()
    )
    rows = (
        db.query(ConceptNode, func.coalesce(mention_counts.c.mentions, 0))
        .outerjoin(mention_counts, ConceptNode.id == mention_counts.c.concept_id)
        .order_by(func.coalesce(mention_counts.c.mentions, 0).desc())
        .limit(limit)
        .all()
    )
    node_ids = {node.id for node, _ in rows}

    edges = (
        db.query(ConceptEdge)
        .filter(ConceptEdge.source_id.in_(node_ids), ConceptEdge.target_id.in_(node_ids))
        .all()
    )

    return {
        "nodes": [
            {
                "id": str(node.id),
                "name": node.name,
                "type": node.type,
                "mentions": int(mentions),
            }
            for node, mentions in rows
        ],
        "edges": [
            {
                "source": str(e.source_id),
                "target": str(e.target_id),
                "relation": e.relation,
                "arxiv_id": e.arxiv_id,
            }
            for e in edges
        ],
    }


@router.get("/concepts/{concept_name}/papers", summary="Papers mentioning a concept")
async def concept_papers(
    concept_name: str,
    db=Depends(get_db_session),
):
    from src.models.paper import ConceptMention, ConceptNode, Paper

    node = (
        db.query(ConceptNode)
        .filter(ConceptNode.canonical_name == concept_name.strip().lower())
        .first()
    ) or (
        db.query(ConceptNode).filter(ConceptNode.name.ilike(f"%{concept_name}%")).first()
    )
    if not node:
        return {"concept": concept_name, "papers": []}

    papers = (
        db.query(Paper)
        .join(ConceptMention, ConceptMention.arxiv_id == Paper.arxiv_id)
        .filter(ConceptMention.concept_id == node.id)
        .all()
    )
    return {
        "concept": node.name,
        "type": node.type,
        "papers": [
            {"arxiv_id": p.arxiv_id, "title": p.title, "published_date": str(p.published_date or "")[:10]}
            for p in papers
        ],
    }
