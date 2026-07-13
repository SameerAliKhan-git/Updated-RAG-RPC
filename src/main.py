"""Corpus — FastAPI application factory and lifespan management."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import get_settings

logger = structlog.get_logger(__name__)


def _configure_logging() -> None:
    """Set up structlog for consistent structured logging."""
    settings = get_settings()
    log_level = logging.DEBUG if settings.debug else logging.INFO

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer() if settings.debug else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown.

    Initializes and tears down connections to Postgres, OpenSearch, and Redis.
    """
    settings = get_settings()
    _configure_logging()
    logger.info("corpus.startup", environment=settings.environment, debug=settings.debug)

    # ── Startup: initialize connection pools ──
    from src.db.opensearch import create_opensearch_client
    from src.db.postgres import create_engine_and_session
    from src.services.redis_client import create_redis_client

    # PostgreSQL
    engine, session_factory = create_engine_and_session(settings.postgres.database_url)
    app.state.db_engine = engine
    app.state.db_session_factory = session_factory
    logger.info("corpus.postgres.connected")

    # OpenSearch
    app.state.opensearch = create_opensearch_client(settings.opensearch.host)
    logger.info("corpus.opensearch.connected", host=settings.opensearch.host)

    # Redis
    app.state.redis = await create_redis_client(settings.redis)
    logger.info("corpus.redis.connected", host=settings.redis.host)

    yield

    # ── Shutdown: close connections ──
    logger.info("corpus.shutdown")

    if hasattr(app.state, "redis") and app.state.redis:
        await app.state.redis.close()
        logger.info("corpus.redis.disconnected")

    if hasattr(app.state, "opensearch") and app.state.opensearch:
        app.state.opensearch.close()
        logger.info("corpus.opensearch.disconnected")

    if hasattr(app.state, "db_engine") and app.state.db_engine:
        app.state.db_engine.dispose()
        logger.info("corpus.postgres.disconnected")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Corpus",
        description="Agentic RAG system for research papers — every answer cited to its source.",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ── CORS ──
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.debug else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ──
    from src.routers.health import router as health_router
    from src.routers.ask import router as ask_router
    from src.routers.feedback import router as feedback_router

    app.include_router(health_router, prefix="/api/v1", tags=["health"])
    app.include_router(ask_router, prefix="/api/v1", tags=["rag"])
    app.include_router(feedback_router, prefix="/api/v1", tags=["feedback"])

    return app


# Module-level app instance for uvicorn
app = create_app()
