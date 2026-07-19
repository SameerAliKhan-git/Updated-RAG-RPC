"""Corpus — deep-research endpoints (background literature review generation)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.middleware.auth import verify_api_key
from src.middleware.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["research"],
    dependencies=[Depends(verify_api_key)],
)


class ResearchRequest(BaseModel):
    topic: str = Field(..., min_length=3, max_length=300)
    collection_id: str | None = None


@router.post(
    "/research",
    summary="Start a deep-research job (background literature review)",
    dependencies=[Depends(rate_limiter)],
)
async def start_research(
    body: ResearchRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
    from src.services.deep_research import new_research_id, run_deep_research
    from src.services.guardrails import sanitize_query

    topic, _flags = sanitize_query(body.topic)
    rid = new_research_id()
    background_tasks.add_task(run_deep_research, rid, topic, body.collection_id, request.app.state)
    logger.info(f"Deep research {rid} started: {topic!r}")
    return {"id": rid, "status": "planning", "topic": topic}


@router.get("/research/{rid}", summary="Deep-research job status and result")
async def research_status(rid: str, request: Request):
    from src.services.deep_research import get_research

    state = await get_research(request.app.state.redis, rid)
    if state is None:
        raise HTTPException(status_code=404, detail=f"No research job {rid}.")
    return state
