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


_S2_BASE = "https://api.semanticscholar.org/graph/v1"
_S2_FIELDS = "title,year,citationCount,externalIds"


def _s2_entry(item: dict, db_ids: set[str]) -> dict | None:
    """Normalize one Semantic Scholar citation/reference record."""
    paper = item.get("citingPaper") or item.get("citedPaper") or item
    ext = paper.get("externalIds") or {}
    arxiv_id = ext.get("ArXiv")
    return {
        "title": paper.get("title", ""),
        "year": paper.get("year"),
        "citation_count": paper.get("citationCount", 0),
        "arxiv_id": arxiv_id,
        "in_corpus": arxiv_id in db_ids if arxiv_id else False,
        "ingestable": bool(arxiv_id),
    }


@router.get("/papers/{arxiv_id}/related", summary="Related work via Semantic Scholar (free API)")
async def related_work(
    arxiv_id: str,
    db=Depends(get_db_session),
):
    """Papers this one cites (references) and papers citing it, ranked by citation count."""
    import httpx

    from src.models.paper import Paper

    db_ids = {row[0] for row in db.query(Paper.arxiv_id).all()}

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            refs_resp, cits_resp = (
                await client.get(
                    f"{_S2_BASE}/paper/arXiv:{arxiv_id}/references",
                    params={"fields": _S2_FIELDS, "limit": 30},
                ),
                await client.get(
                    f"{_S2_BASE}/paper/arXiv:{arxiv_id}/citations",
                    params={"fields": _S2_FIELDS, "limit": 30},
                ),
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Semantic Scholar unreachable: {e}") from e

    if refs_resp.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Semantic Scholar has no record for arXiv:{arxiv_id}.")
    if refs_resp.status_code == 429 or cits_resp.status_code == 429:
        raise HTTPException(status_code=429, detail="Semantic Scholar rate limit hit — try again in a minute.")

    def top(items: list[dict]) -> list[dict]:
        entries = [e for e in (_s2_entry(i, db_ids) for i in items) if e and e["title"]]
        entries.sort(key=lambda e: e.get("citation_count") or 0, reverse=True)
        return entries[:12]

    return {
        "references": top(refs_resp.json().get("data", []) if refs_resp.status_code == 200 else []),
        "citations": top(cits_resp.json().get("data", []) if cits_resp.status_code == 200 else []),
    }


@router.post("/papers/{arxiv_id}/ingest", summary="Queue ingestion of a paper by arXiv id")
async def ingest_related(
    arxiv_id: str,
    request: Request,
    db=Depends(get_db_session),
):
    """One-click ingest for discovered related work (uses the existing arq path)."""
    from src.models.paper import Paper
    from src.services.redis_services import RedisServicesManager

    if db.query(Paper).filter(Paper.arxiv_id == arxiv_id).first():
        return {"status": "already_present", "arxiv_id": arxiv_id}

    ok = await RedisServicesManager(request.app.state.redis).enqueue_paper_ingestion(arxiv_id)
    if not ok:
        raise HTTPException(status_code=502, detail="Could not queue ingestion.")
    return {"status": "queued", "arxiv_id": arxiv_id}


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
