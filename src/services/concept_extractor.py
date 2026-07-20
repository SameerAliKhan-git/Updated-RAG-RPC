"""Corpus — offline concept-graph extraction (run nightly via Airflow, or
on demand via POST /concepts/build for stacks without the airflow profile).

One fast-LLM call per unprocessed paper over title + abstract + section titles.
Entities are canonicalized by normalized-name match first, then bge-m3
cosine similarity (> 0.92, same type) against existing canonical names.
Every embedding-merge is logged for auditing.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from src.agents.prompts import CONCEPT_EXTRACTION_PROMPT
from src.services.llm_adapter import call_fast_llm, parse_json_response

logger = logging.getLogger(__name__)

BUILD_STATUS_KEY = "corpus:concept_build:status"
BUILD_STATUS_TTL = 60 * 60 * 6  # 6h — long enough to see the result, short enough not to linger

ALLOWED_TYPES = {"method", "dataset", "task", "metric"}
ALLOWED_RELATIONS = {"uses", "improves_on", "evaluated_on", "compares_to"}
MERGE_THRESHOLD = 0.92
MAX_ENTITIES = 8


def _normalize(name: str) -> str:
    return " ".join(name.lower().strip().split())


async def _canonicalize(db, name: str, concept_type: str, embedder):
    """Find-or-create a ConceptNode, merging near-duplicates of the same type."""
    from src.models.paper import ConceptNode

    normalized = _normalize(name)

    node = (
        db.query(ConceptNode).filter(ConceptNode.canonical_name == normalized, ConceptNode.type == concept_type).first()
    )
    if node:
        return node

    # Embedding-similarity merge against same-type canonical names
    peers = db.query(ConceptNode).filter(ConceptNode.type == concept_type).all()
    if peers and embedder is not None:
        try:
            import math

            names = [p.canonical_name for p in peers]
            vectors = await embedder.embed_passages([normalized, *names])
            target, peer_vecs = vectors[0], vectors[1:]

            def cos(a: list[float], b: list[float]) -> float:
                dot = sum(x * y for x, y in zip(a, b, strict=True))
                na = math.sqrt(sum(x * x for x in a))
                nb = math.sqrt(sum(x * x for x in b))
                return dot / (na * nb) if na and nb else 0.0

            scores = [cos(target, v) for v in peer_vecs]
            best_idx = max(range(len(scores)), key=lambda i: scores[i])
            if scores[best_idx] > MERGE_THRESHOLD:
                logger.info(
                    f"Concept merge: '{normalized}' → '{peers[best_idx].canonical_name}' "
                    f"({concept_type}, sim={scores[best_idx]:.3f})"
                )
                return peers[best_idx]
        except Exception as e:
            logger.warning(f"Concept similarity merge failed for '{normalized}': {e}")

    node = ConceptNode(name=name.strip(), canonical_name=normalized, type=concept_type)
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


async def extract_concepts_for_paper(db, paper, embedder) -> dict:
    """Extract and persist concepts + relations for one paper. Returns stats."""
    from src.models.paper import Chunk, ConceptEdge, ConceptMention, ConceptNode

    section_titles = [
        row[0] for row in db.query(Chunk.section_title).filter(Chunk.paper_id == paper.id).distinct().limit(15).all()
    ]

    prompt = CONCEPT_EXTRACTION_PROMPT.format(
        title=paper.title,
        abstract=(paper.abstract or "")[:1500],
        sections=", ".join(section_titles[:15]),
    )
    response = await call_fast_llm(messages=[{"role": "user", "content": prompt}], temperature=0.0, max_tokens=512)
    parsed = parse_json_response(response)

    entities = [
        e
        for e in parsed.get("entities", [])[:MAX_ENTITIES]
        if isinstance(e, dict) and e.get("name") and e.get("type") in ALLOWED_TYPES
    ]
    entity_names = {_normalize(e["name"]) for e in entities}

    nodes: dict[str, ConceptNode] = {}
    for entity in entities:
        node = await _canonicalize(db, entity["name"], entity["type"], embedder)
        nodes[_normalize(entity["name"])] = node
        exists = (
            db.query(ConceptMention)
            .filter(ConceptMention.concept_id == node.id, ConceptMention.arxiv_id == paper.arxiv_id)
            .first()
        )
        if not exists:
            db.add(ConceptMention(concept_id=node.id, arxiv_id=paper.arxiv_id))

    edges_added = 0
    for rel in parsed.get("relations", []):
        if not isinstance(rel, dict) or rel.get("relation") not in ALLOWED_RELATIONS:
            continue
        src_key, tgt_key = _normalize(rel.get("source", "")), _normalize(rel.get("target", ""))
        # Drop relations referencing entities the model didn't list
        if src_key not in entity_names or tgt_key not in entity_names or src_key == tgt_key:
            continue
        src_node, tgt_node = nodes.get(src_key), nodes.get(tgt_key)
        if src_node is None or tgt_node is None:
            continue
        exists = (
            db.query(ConceptEdge)
            .filter(
                ConceptEdge.source_id == src_node.id,
                ConceptEdge.target_id == tgt_node.id,
                ConceptEdge.relation == rel["relation"],
                ConceptEdge.arxiv_id == paper.arxiv_id,
            )
            .first()
        )
        if not exists:
            db.add(
                ConceptEdge(
                    source_id=src_node.id,
                    target_id=tgt_node.id,
                    relation=rel["relation"],
                    arxiv_id=paper.arxiv_id,
                )
            )
            edges_added += 1

    # Mark attempted even on empty extraction — never loop on a bad paper
    paper.concepts_extracted_at = datetime.now(UTC)
    db.commit()
    return {"entities": len(entities), "edges": edges_added}


async def build_concept_graph(limit: int = 50) -> dict:
    """Process up to `limit` papers without extracted concepts."""
    from src.config import get_settings
    from src.db.postgres import create_engine_and_session
    from src.models.paper import Paper
    from src.services.embedding_client import create_embedding_client

    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings.postgres.database_url)
    db = session_factory()
    embedder = create_embedding_client()

    stats = {"papers": 0, "entities": 0, "edges": 0, "errors": 0}
    try:
        papers = (
            db.query(Paper)
            .filter(Paper.concepts_extracted_at.is_(None), Paper.pdf_processed.is_(True))
            .order_by(Paper.created_at)
            .limit(limit)
            .all()
        )
        logger.info(f"Concept graph: {len(papers)} papers to process")
        for paper in papers:
            try:
                result = await extract_concepts_for_paper(db, paper, embedder)
                stats["papers"] += 1
                stats["entities"] += result["entities"]
                stats["edges"] += result["edges"]
            except Exception as e:
                logger.error(f"Concept extraction failed for {paper.arxiv_id}: {e}")
                stats["errors"] += 1
                db.rollback()
        return stats
    finally:
        await embedder.close()
        db.close()
        engine.dispose()


async def get_build_status(redis) -> dict[str, Any]:
    """Current/last status of the on-demand concept-graph build, for the Galaxy
    empty-state UI to poll. Returns {"status": "idle"} if never run."""
    raw = await redis.get(BUILD_STATUS_KEY)
    if raw is None:
        return {"status": "idle"}
    return json.loads(raw)


async def run_concept_graph_job(redis, limit: int = 200) -> None:
    """Background-task entry point for POST /concepts/build — runs
    build_concept_graph() and records progress/result in Redis so the
    frontend can poll without waiting on Airflow's nightly schedule."""
    started_at = datetime.now(UTC).isoformat()
    await redis.set(
        BUILD_STATUS_KEY,
        json.dumps({"status": "running", "started_at": started_at}),
        ex=BUILD_STATUS_TTL,
    )
    try:
        stats = await build_concept_graph(limit=limit)
        await redis.set(
            BUILD_STATUS_KEY,
            json.dumps({"status": "done", "started_at": started_at, "stats": stats}),
            ex=BUILD_STATUS_TTL,
        )
    except Exception as e:
        logger.error(f"Concept graph on-demand build failed: {e}")
        await redis.set(
            BUILD_STATUS_KEY,
            json.dumps({"status": "error", "started_at": started_at, "error": str(e)}),
            ex=BUILD_STATUS_TTL,
        )


if __name__ == "__main__":
    import asyncio

    print(asyncio.run(build_concept_graph()))
