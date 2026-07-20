"""Corpus — Integrations Router Integration Tests (Semantic Scholar + Zotero)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client_with_mocks():
    from src.routers.integrations import router

    app = FastAPI()
    app.state.redis = AsyncMock()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def _mock_db_dependency(app: FastAPI, db: MagicMock):
    from src.dependencies import get_db_session

    app.dependency_overrides[get_db_session] = lambda: db


def _fake_response(status_code: int, payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    return resp


def test_related_work_ranks_by_citation_count_and_flags_in_corpus(client_with_mocks):
    db = MagicMock()
    db.query.return_value.all.return_value = [("1706.03762",)]
    _mock_db_dependency(client_with_mocks.app, db)

    refs_payload = {
        "data": [
            {"citingPaper": {"title": "Low cite", "citationCount": 2, "externalIds": {"ArXiv": "2001.00001"}}},
            {"citingPaper": {"title": "High cite", "citationCount": 500, "externalIds": {"ArXiv": "1706.03762"}}},
        ]
    }
    cits_payload = {"data": []}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.side_effect = [
            _fake_response(200, refs_payload),
            _fake_response(200, cits_payload),
        ]
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        resp = client_with_mocks.get("/api/v1/papers/1706.03762/related")

    assert resp.status_code == 200
    data = resp.json()
    assert data["references"][0]["title"] == "High cite"  # ranked by citation_count desc
    assert data["references"][0]["in_corpus"] is True
    assert data["references"][1]["in_corpus"] is False
    assert data["citations"] == []


def test_related_work_returns_404_when_semantic_scholar_has_no_record(client_with_mocks):
    db = MagicMock()
    db.query.return_value.all.return_value = []
    _mock_db_dependency(client_with_mocks.app, db)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.side_effect = [_fake_response(404, {}), _fake_response(404, {})]
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        resp = client_with_mocks.get("/api/v1/papers/0000.00000/related")

    assert resp.status_code == 404


def test_related_work_returns_502_when_semantic_scholar_unreachable(client_with_mocks):
    """A network failure talking to Semantic Scholar must surface as a clear 502,
    not an unhandled 500 — this is an external dependency the user can retry."""
    db = MagicMock()
    db.query.return_value.all.return_value = []
    _mock_db_dependency(client_with_mocks.app, db)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("connection refused")
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        resp = client_with_mocks.get("/api/v1/papers/1706.03762/related")

    assert resp.status_code == 502


def test_related_work_returns_429_on_rate_limit(client_with_mocks):
    db = MagicMock()
    db.query.return_value.all.return_value = []
    _mock_db_dependency(client_with_mocks.app, db)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.side_effect = [_fake_response(429, {}), _fake_response(200, {"data": []})]
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        resp = client_with_mocks.get("/api/v1/papers/1706.03762/related")

    assert resp.status_code == 429


def test_ingest_related_returns_already_present_without_queueing(client_with_mocks):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = MagicMock()  # paper exists
    _mock_db_dependency(client_with_mocks.app, db)

    resp = client_with_mocks.post("/api/v1/papers/1706.03762/ingest")
    assert resp.status_code == 200
    assert resp.json() == {"status": "already_present", "arxiv_id": "1706.03762"}


def test_ingest_related_queues_new_paper(client_with_mocks):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    _mock_db_dependency(client_with_mocks.app, db)

    with patch("src.services.redis_services.RedisServicesManager") as mock_mgr_cls:
        mock_mgr_cls.return_value.enqueue_paper_ingestion = AsyncMock(return_value=True)
        resp = client_with_mocks.post("/api/v1/papers/2001.00001/ingest")

    assert resp.status_code == 200
    assert resp.json() == {"status": "queued", "arxiv_id": "2001.00001"}


def test_zotero_import_gives_actionable_hint_when_local_app_not_running(client_with_mocks):
    """A ConnectError from the local Zotero client should surface a hint about the
    desktop app needing to be running on port 23119, not a bare 502."""
    db = MagicMock()
    _mock_db_dependency(client_with_mocks.app, db)

    with patch("src.services.zotero_client.fetch_items_local", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.side_effect = ConnectionError("connection refused")
        resp = client_with_mocks.post("/api/v1/integrations/zotero/import", json={"use_local": True})

    assert resp.status_code == 502
    assert "Zotero desktop app" in resp.json()["detail"]


def test_zotero_import_web_mode_requires_credentials(client_with_mocks):
    db = MagicMock()
    _mock_db_dependency(client_with_mocks.app, db)

    resp = client_with_mocks.post("/api/v1/integrations/zotero/import", json={"use_local": False})
    assert resp.status_code == 422
