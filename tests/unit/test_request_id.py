"""Corpus — request-id correlation middleware tests."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.middleware.request_id import REQUEST_ID_HEADER, RequestIDMiddleware


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    return app


def test_generates_request_id_when_absent():
    client = TestClient(_app())
    resp = client.get("/ping")
    assert resp.status_code == 200
    rid = resp.headers.get(REQUEST_ID_HEADER)
    assert rid and len(rid) == 12


def test_echoes_incoming_request_id():
    """A caller-supplied X-Request-ID is preserved so a client can correlate
    its own logs with the server's."""
    client = TestClient(_app())
    resp = client.get("/ping", headers={REQUEST_ID_HEADER: "trace-abc-123"})
    assert resp.headers.get(REQUEST_ID_HEADER) == "trace-abc-123"


def test_ids_differ_across_requests():
    client = TestClient(_app())
    a = client.get("/ping").headers[REQUEST_ID_HEADER]
    b = client.get("/ping").headers[REQUEST_ID_HEADER]
    assert a != b
