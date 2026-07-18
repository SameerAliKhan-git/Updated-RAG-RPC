"""Corpus — Web Frontend Server.

Serves the custom Stitch-designed single-page application on port 7860.
The SPA connects directly to the FastAPI backend API on port 8000.

Run standalone:
    python -m src.clients.gradio_app
"""

from __future__ import annotations

import logging
import os

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

app = FastAPI(title="Corpus Frontend", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def index():
    """Serve the main SPA page."""
    return FileResponse(
        os.path.join(STATIC_DIR, "index.html"),
        media_type="text/html",
    )


@app.get("/health")
async def health():
    """Simple health check for the frontend server."""
    return {"status": "ok"}


if __name__ == "__main__":
    port = int(os.getenv("GRADIO_SERVER_PORT", "7860"))
    logger.info(f"Starting Corpus frontend on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
