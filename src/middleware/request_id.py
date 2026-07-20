"""Corpus — request correlation IDs.

Assigns every request a short id, binds it to structlog's contextvars (which
main.py's logging config already merges into every log line), and echoes it
back as the X-Request-ID response header. This lets you take the id from a
user's failed answer and pull every log line for that exact request — the
after-the-fact debugging that a streamed SSE pipeline otherwise makes hard.
"""

from __future__ import annotations

import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Bind a per-request correlation id to logs and the response header."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:12]

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()

        response.headers[REQUEST_ID_HEADER] = request_id
        return response
