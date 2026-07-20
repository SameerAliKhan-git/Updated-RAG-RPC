"""Corpus — Concepts Router Integration Tests (Research Galaxy API)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client_with_mocks():
    from src.routers.concepts import router

    app = FastAPI()
    app.state.db_session_factory = MagicMock()
    app.state.redis = AsyncMock()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def _mock_db_dependency(app: FastAPI, db: MagicMock):
    from src.dependencies import get_db_session

    app.dependency_overrides[get_db_session] = lambda: db


def test_concept_graph_returns_nodes_and_edges(client_with_mocks):
    node = MagicMock(id="n1", type="method")
    # MagicMock(name=...) sets the mock's repr, not an attribute — must assign after construction.
    node.name = "Attention"
    edge = MagicMock(source_id="n1", target_id="n2", relation="uses", arxiv_id="1706.03762")

    db = MagicMock()
    db.query.return_value.group_by.return_value.subquery.return_value = MagicMock()
    db.query.return_value.outerjoin.return_value.order_by.return_value.limit.return_value.all.return_value = [(node, 3)]
    db.query.return_value.filter.return_value.all.return_value = [edge]
    _mock_db_dependency(client_with_mocks.app, db)

    resp = client_with_mocks.get("/api/v1/concepts/graph")
    assert resp.status_code == 200
    data = resp.json()
    assert data["nodes"][0]["name"] == "Attention"
    assert data["nodes"][0]["mentions"] == 3
    assert data["edges"][0]["relation"] == "uses"


def test_concept_graph_empty_when_nothing_extracted_yet(client_with_mocks):
    db = MagicMock()
    db.query.return_value.group_by.return_value.subquery.return_value = MagicMock()
    db.query.return_value.outerjoin.return_value.order_by.return_value.limit.return_value.all.return_value = []
    db.query.return_value.filter.return_value.all.return_value = []
    _mock_db_dependency(client_with_mocks.app, db)

    resp = client_with_mocks.get("/api/v1/concepts/graph")
    assert resp.status_code == 200
    assert resp.json() == {"nodes": [], "edges": []}


def test_concept_papers_returns_empty_when_concept_unknown(client_with_mocks):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    _mock_db_dependency(client_with_mocks.app, db)

    resp = client_with_mocks.get("/api/v1/concepts/nonexistent-concept/papers")
    assert resp.status_code == 200
    assert resp.json() == {"concept": "nonexistent-concept", "papers": []}


def test_trigger_build_starts_job_when_idle(client_with_mocks):
    with patch("src.services.concept_extractor.get_build_status", new_callable=AsyncMock) as mock_status:
        mock_status.return_value = {"status": "idle"}
        resp = client_with_mocks.post("/api/v1/concepts/build")

    assert resp.status_code == 200
    assert resp.json()["status"] == "started"


def test_trigger_build_reports_already_running_instead_of_double_starting(client_with_mocks):
    """A second POST /concepts/build while one is in flight must not enqueue a
    duplicate job — the whole point of tracking status is avoiding concurrent runs."""
    with patch("src.services.concept_extractor.get_build_status", new_callable=AsyncMock) as mock_status:
        mock_status.return_value = {"status": "running", "started_at": "2026-01-01T00:00:00"}
        resp = client_with_mocks.post("/api/v1/concepts/build")

    assert resp.status_code == 200
    assert resp.json()["status"] == "already_running"


def test_build_status_reports_idle_when_never_run(client_with_mocks):
    client_with_mocks.app.state.redis.get.return_value = None
    resp = client_with_mocks.get("/api/v1/concepts/build/status")
    assert resp.status_code == 200
    assert resp.json() == {"status": "idle"}


def test_build_status_reports_done_with_stats(client_with_mocks):
    client_with_mocks.app.state.redis.get.return_value = json.dumps(
        {"status": "done", "stats": {"papers": 5, "entities": 12, "edges": 4, "errors": 0}}
    )
    resp = client_with_mocks.get("/api/v1/concepts/build/status")
    assert resp.status_code == 200
    assert resp.json()["stats"]["papers"] == 5
