"""Corpus — external integrations (Zotero import)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.dependencies import get_db_session
from src.middleware.auth import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["integrations"],
    dependencies=[Depends(verify_api_key)],
)


class ZoteroImportRequest(BaseModel):
    use_local: bool = True
    api_key: str | None = None
    zotero_user_id: str | None = None


@router.post("/integrations/zotero/import", summary="Import arXiv papers from a Zotero library")
async def zotero_import(
    body: ZoteroImportRequest,
    request: Request,
    db=Depends(get_db_session),
):
    from src.models.paper import Paper
    from src.services.redis_services import RedisServicesManager
    from src.services.zotero_client import classify_items, fetch_items_local, fetch_items_web

    try:
        if body.use_local:
            items = await fetch_items_local()
        else:
            if not body.api_key or not body.zotero_user_id:
                raise HTTPException(
                    status_code=422, detail="Web import needs api_key and zotero_user_id."
                )
            items = await fetch_items_web(body.api_key, body.zotero_user_id)
    except HTTPException:
        raise
    except Exception as e:
        hint = (
            "Is the Zotero desktop app running? (its local API serves on port 23119)"
            if body.use_local
            else "Check the API key and user id."
        )
        raise HTTPException(status_code=502, detail=f"Zotero fetch failed: {e}. {hint}") from e

    resolvable, skipped = classify_items(items)

    existing_ids = {
        row[0]
        for row in db.query(Paper.arxiv_id)
        .filter(Paper.arxiv_id.in_([r["arxiv_id"] for r in resolvable]))
        .all()
    }

    queued = []
    already_present = []
    redis_mgr = RedisServicesManager(request.app.state.redis)
    for entry in resolvable:
        if entry["arxiv_id"] in existing_ids:
            already_present.append(entry)
            continue
        if await redis_mgr.enqueue_paper_ingestion(entry["arxiv_id"]):
            queued.append(entry)
        else:
            skipped.append({"key": "", "title": entry["title"], "reason": "queueing failed"})

    logger.info(
        f"Zotero import: {len(queued)} queued, {len(already_present)} present, {len(skipped)} skipped"
    )
    return {"queued": queued, "already_present": already_present, "skipped": skipped}
