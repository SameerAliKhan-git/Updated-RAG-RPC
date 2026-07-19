"""Corpus — deep-research mode.

A long-running background job that plans sub-topics, runs the full agentic
pipeline per sub-topic, and assembles a structured, fully-cited survey
document. Progress and the final markdown live in Redis so the UI can poll.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from src.services.llm_adapter import call_fast_llm, parse_json_response

logger = logging.getLogger(__name__)

RESEARCH_KEY = "corpus:research:{rid}"
RESEARCH_TTL = 7 * 24 * 3600

PLANNER_PROMPT = """You are planning a short literature review from a research paper corpus.

Break the topic below into 3 focused sub-questions that together give a reader
a complete picture: fundamentals, key methods/results, and open challenges.

Respond with ONLY valid JSON:
{{"sub_questions": ["<q1>", "<q2>", "<q3>"]}}

Topic: {topic}"""


async def _set(redis, rid: str, payload: dict[str, Any]) -> None:
    await redis.set(RESEARCH_KEY.format(rid=rid), json.dumps(payload), ex=RESEARCH_TTL)


async def get_research(redis, rid: str) -> dict[str, Any] | None:
    raw = await redis.get(RESEARCH_KEY.format(rid=rid))
    return json.loads(raw) if raw else None


def new_research_id() -> str:
    return uuid.uuid4().hex[:12]


async def run_deep_research(
    rid: str,
    topic: str,
    collection_id: str | None,
    app_state,
) -> None:
    """Execute the research job; all state transitions go through Redis."""
    redis = app_state.redis
    state: dict[str, Any] = {
        "id": rid,
        "topic": topic,
        "status": "planning",
        "steps": [],
        "result_markdown": None,
        "started_at": time.time(),
    }

    def step(msg: str) -> None:
        state["steps"].append(msg)
        logger.info(f"[research {rid}] {msg}")

    try:
        await _set(redis, rid, state)

        # 1. Plan sub-questions
        step(f'Planning sub-topics for "{topic}"...')
        await _set(redis, rid, state)
        response = await call_fast_llm(
            messages=[{"role": "user", "content": PLANNER_PROMPT.format(topic=topic)}],
            temperature=0.2,
            max_tokens=384,
        )
        sub_questions = parse_json_response(response).get("sub_questions", [])[:4]
        if not sub_questions:
            sub_questions = [topic]
        step(f"Planned {len(sub_questions)} sub-questions")
        state["status"] = "researching"
        await _set(redis, rid, state)

        # 2. Resolve collection scope once
        filters: dict[str, Any] = {}
        if collection_id:
            from src.models.paper import CollectionPaper, Paper

            db = app_state.db_session_factory()
            try:
                ids = [
                    row[0]
                    for row in db.query(Paper.arxiv_id)
                    .join(CollectionPaper, CollectionPaper.paper_id == Paper.id)
                    .filter(CollectionPaper.collection_id == collection_id)
                    .all()
                ]
            finally:
                db.close()
            if ids:
                filters["arxiv_ids"] = ids

        # 3. Run the full pipeline per sub-question
        from src.agents.rag_graph import ask_corpus
        from src.agents.tools import AgentToolkit
        from src.retrieval.hybrid_search import HybridSearchService
        from src.retrieval.reranker import create_reranker

        sections: list[dict[str, Any]] = []
        for i, sq in enumerate(sub_questions, start=1):
            step(f"Researching {i}/{len(sub_questions)}: {sq}")
            await _set(redis, rid, state)

            db = app_state.db_session_factory()
            search_service = HybridSearchService(app_state.opensearch)
            reranker = create_reranker()
            toolkit = AgentToolkit(
                search_service=search_service,
                reranker=reranker,
                db_session=db,
                redis_client=redis,
            )
            try:
                result = await ask_corpus(query=sq, toolkit=toolkit, filters=filters or None)
                sections.append({"question": sq, **result})
            except Exception as e:
                logger.error(f"[research {rid}] sub-question failed: {e}")
                sections.append(
                    {"question": sq, "answer_markdown": f"_Research for this section failed: {e}_", "citations": []}
                )
            finally:
                await search_service.close()
                await reranker.close()
                db.close()

        # 4. Assemble the survey with globally renumbered citations
        step("Assembling survey document...")
        await _set(redis, rid, state)
        state["result_markdown"] = _assemble(topic, sections)
        state["status"] = "done"
        state["finished_at"] = time.time()
        step("Done")
        await _set(redis, rid, state)

    except Exception as e:
        logger.error(f"[research {rid}] failed: {e}", exc_info=True)
        state["status"] = "failed"
        state["error"] = str(e)
        await _set(redis, rid, state)


def _assemble(topic: str, sections: list[dict[str, Any]]) -> str:
    """Merge per-section answers into one document with global citation numbering."""
    import re

    lines = [f"# {topic}", "", "_Generated by Corpus deep research — every claim cited to its source._", ""]
    all_citations: list[dict[str, Any]] = []

    for section in sections:
        offset = len(all_citations)
        body = section.get("answer_markdown", "")
        citations = section.get("citations", [])

        # Renumber [n] → [n+offset] (descending to avoid double-substitution)
        for cite in sorted(citations, key=lambda c: c.get("id", 0), reverse=True):
            old, new = cite.get("id", 0), cite.get("id", 0) + offset
            body = re.sub(rf"\[{old}\]", f"[{new}]", body)
        for cite in sorted(citations, key=lambda c: c.get("id", 0)):
            all_citations.append({**cite, "id": cite.get("id", 0) + offset})

        lines.append(f"## {section['question']}")
        lines.append("")
        lines.append(body)
        lines.append("")

    if all_citations:
        lines.append("## References")
        lines.append("")
        for c in all_citations:
            page = f", p. {c['page']}" if c.get("page") else ""
            lines.append(
                f"[{c['id']}] {', '.join(c.get('authors', [])[:3])} — *{c.get('paper_title', '')}* "
                f"(arXiv:{c.get('arxiv_id', '')}{page})"
            )
    return "\n".join(lines)
