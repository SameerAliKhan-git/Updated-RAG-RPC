"""Corpus — Zotero import client.

Two free paths into the corpus:
- Local: Zotero desktop's built-in HTTP API (no key needed, desktop must run).
- Web: api.zotero.org with a free API key.

Items resolvable to an arXiv id are queued through the existing arq ingestion
path; everything else is reported as skipped with a reason.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from src.config import get_settings

logger = logging.getLogger(__name__)

_ARXIV_PATTERNS = [
    re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", re.I),
    re.compile(r"arXiv:\s*(\d{4}\.\d{4,5})", re.I),
    re.compile(r"10\.48550/arXiv\.(\d{4}\.\d{4,5})", re.I),
]

PAGE_SIZE = 100
MAX_ITEMS = 2000


def extract_arxiv_id(item: dict[str, Any]) -> str | None:
    """Pull an arXiv id out of a Zotero item's url/extra/DOI/archive fields."""
    data = item.get("data", item)
    haystacks = [
        str(data.get("url", "")),
        str(data.get("extra", "")),
        str(data.get("DOI", "")),
        str(data.get("archiveLocation", "")),
        str(data.get("archive", "")),
    ]
    for text in haystacks:
        for pattern in _ARXIV_PATTERNS:
            m = pattern.search(text)
            if m:
                return m.group(1)
    return None


async def fetch_items_local() -> list[dict[str, Any]]:
    """Fetch top-level items from the Zotero desktop local API."""
    settings = get_settings()
    base = settings.zotero_local_url.rstrip("/")
    items: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=20.0) as client:
        start = 0
        while start < MAX_ITEMS:
            resp = await client.get(
                f"{base}/api/users/0/items",
                params={"format": "json", "limit": PAGE_SIZE, "start": start},
            )
            resp.raise_for_status()
            page = resp.json()
            if not page:
                break
            items.extend(page)
            if len(page) < PAGE_SIZE:
                break
            start += PAGE_SIZE
    return items


async def fetch_items_web(api_key: str, user_id: str) -> list[dict[str, Any]]:
    """Fetch top-level items from the Zotero web API."""
    items: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        start = 0
        while start < MAX_ITEMS:
            resp = await client.get(
                f"https://api.zotero.org/users/{user_id}/items",
                params={"format": "json", "limit": PAGE_SIZE, "start": start, "itemType": "-attachment"},
                headers={"Zotero-API-Key": api_key},
            )
            resp.raise_for_status()
            page = resp.json()
            if not page:
                break
            items.extend(page)
            if len(page) < PAGE_SIZE:
                break
            start += PAGE_SIZE
    return items


def classify_items(items: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """Split items into (resolvable, skipped-with-reason)."""
    resolvable: list[dict] = []
    skipped: list[dict] = []
    for item in items:
        data = item.get("data", item)
        item_type = data.get("itemType", "")
        title = data.get("title", "(untitled)")
        if item_type in ("attachment", "note", "annotation"):
            continue  # structural children, not bibliography entries
        arxiv_id = extract_arxiv_id(item)
        if arxiv_id:
            resolvable.append({"arxiv_id": arxiv_id, "title": title})
        else:
            skipped.append({"key": data.get("key", ""), "title": title, "reason": "no arXiv id found"})
    return resolvable, skipped
