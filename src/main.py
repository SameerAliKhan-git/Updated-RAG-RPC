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

    # ── Fail loud on insecure auth defaults outside local dev ──
    # In development, verify_api_key() short-circuits auth entirely — fine for
    # localhost. Outside development, an unset or still-placeholder API_KEY
    # means every request is either rejected or (worse) accepted using the
    # literal string from .env.example, which is public. Refuse to boot with
    # ENVIRONMENT=production in that state; warn loudly for any other non-dev value.
    _PLACEHOLDER_API_KEY = "change-me-to-a-real-api-key"
    if settings.environment != "development":
        insecure_key = not settings.api_key or settings.api_key == _PLACEHOLDER_API_KEY
        if insecure_key and settings.environment == "production":
            raise RuntimeError(
                "Refusing to start with ENVIRONMENT=production and no real API_KEY. "
                "Set API_KEY in .env to a strong secret (or set ENVIRONMENT=development "
                "for trusted local-only use)."
            )
        if insecure_key:
            logger.warning(
                "corpus.auth.insecure_default_api_key",
                environment=settings.environment,
                hint="API_KEY is unset or still the .env.example placeholder — "
                "set a real secret before exposing this beyond localhost.",
            )

    # ── Startup: initialize connection pools ──
    from src.db.opensearch import create_opensearch_client
    from src.db.postgres import create_engine_and_session

    # PostgreSQL
    from src.models.paper import Base as PaperBase  # noqa: F401
    from src.services.redis_client import create_redis_client

    engine, session_factory = create_engine_and_session(settings.postgres.database_url)
    PaperBase.metadata.create_all(bind=engine)

    from src.db.migrations import run_startup_migrations

    run_startup_migrations(engine)
    app.state.db_engine = engine
    app.state.db_session_factory = session_factory
    logger.info("corpus.postgres.connected")

    # OpenSearch
    app.state.opensearch = create_opensearch_client(settings.opensearch.host)
    logger.info("corpus.opensearch.connected", host=settings.opensearch.host)

    # Redis
    app.state.redis = await create_redis_client(settings.redis)
    logger.info("corpus.redis.connected", host=settings.redis.host)

    # Embedding + reranker models — load eagerly so requests don't pay the
    # multi-second cold-load cost. Fails loudly on error: broken embeddings
    # must never degrade silently.
    import asyncio as _asyncio

    from src.retrieval.reranker import _get_cross_encoder
    from src.services.embedding_client import warm_embedding_model

    await _asyncio.to_thread(warm_embedding_model)
    logger.info("corpus.embeddings.ready", model=settings.embedding.model_name)

    if settings.reranker.enabled and settings.reranker.backend == "local":
        await _asyncio.to_thread(_get_cross_encoder)
        logger.info("corpus.reranker.ready", model=settings.reranker.model)

    # Optional: pick the largest workable LLM before the first request
    from src.services.model_select import autoselect_models

    await autoselect_models()
    logger.info("corpus.models.active", drafting=settings.litellm.drafting_model, fast=settings.litellm.fast_model)

    # Hourly canary probe — synthetic retrieval + LLM check, surfaced at /health/canary
    import asyncio as _asyncio_canary

    from src.services.canary import canary_loop

    canary_task = _asyncio_canary.create_task(canary_loop(app.state))
    logger.info("corpus.canary.scheduled")

    yield

    # ── Shutdown: close connections ──
    logger.info("corpus.shutdown")
    canary_task.cancel()

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

    # ── Circuit breaker → 503 ──
    from fastapi import Request as _Request
    from fastapi.responses import JSONResponse

    from src.services.resilience import CircuitBreakerOpenException

    @app.exception_handler(CircuitBreakerOpenException)
    async def circuit_breaker_handler(request: _Request, exc: CircuitBreakerOpenException) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": str(exc)},
            headers={"Retry-After": "30"},
        )

    # ── CORS ──
    # Wildcard + credentials is rejected by browsers (spec-invalid), and the old
    # prod branch of [] blocked every cross-origin client. Use an explicit
    # allow-list from CORS_ALLOW_ORIGINS; only enable credentials when the list
    # is explicit (not "*"). The default same-origin nginx deployment needs none
    # of this, but external browser clients now work when configured.
    cors_origins = [o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()]
    allow_all = cors_origins == ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=not allow_all,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Prometheus metrics ──
    from prometheus_client import make_asgi_app

    from src.middleware.metrics import MetricsMiddleware

    app.add_middleware(MetricsMiddleware)
    app.mount("/metrics", make_asgi_app())

    # ── Request correlation IDs (added last → runs first, so every log
    # line, including metrics, carries the request_id) ──
    from src.middleware.request_id import RequestIDMiddleware

    app.add_middleware(RequestIDMiddleware)

    # ── Routers ──
    from src.routers.ask import router as ask_router
    from src.routers.collections import router as collections_router
    from src.routers.concepts import router as concepts_router
    from src.routers.eval import router as eval_router
    from src.routers.feedback import router as feedback_router
    from src.routers.health import router as health_router
    from src.routers.integrations import router as integrations_router
    from src.routers.sessions import router as sessions_router

    app.include_router(health_router, prefix="/api/v1", tags=["health"])
    app.include_router(ask_router, prefix="/api/v1", tags=["rag"])
    app.include_router(feedback_router, prefix="/api/v1", tags=["feedback"])
    app.include_router(eval_router, prefix="/api/v1", tags=["evaluation"])
    app.include_router(collections_router, prefix="/api/v1", tags=["collections"])
    app.include_router(sessions_router, prefix="/api/v1", tags=["sessions"])
    app.include_router(integrations_router, prefix="/api/v1", tags=["integrations"])
    app.include_router(concepts_router, prefix="/api/v1", tags=["concepts"])

    from src.routers.research import router as research_router

    app.include_router(research_router, prefix="/api/v1", tags=["research"])

    return app


# Module-level app instance for uvicorn
app = create_app()
