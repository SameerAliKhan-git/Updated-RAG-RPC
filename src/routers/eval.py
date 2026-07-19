"""Corpus — Evaluation and Langfuse Diagnostics Router.

Provides endpoints to trigger background evaluation runs, query evaluation metrics status,
and check Langfuse tracing configurations.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from src.config import get_settings
from src.middleware.auth import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["evaluation"],
    dependencies=[Depends(verify_api_key)],
)


async def run_evaluation_task(app_redis, sample_rate: float, mode: str = "traces", limit: int = 10) -> None:
    """FastAPI background task to execute RAGAS evaluation and store results in Redis."""
    try:
        await app_redis.set(
            "corpus:eval:status",
            json.dumps(
                {
                    "status": "RUNNING",
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "scores": None,
                    "mode": mode,
                }
            ),
        )

        from src.services.ragas_sampler import evaluate_golden_set, sample_traces_and_evaluate

        if mode == "golden":
            scores = await evaluate_golden_set(limit=limit)
        else:
            scores = await sample_traces_and_evaluate(sample_rate=sample_rate)

        await app_redis.set(
            "corpus:eval:status",
            json.dumps(
                {
                    "status": "COMPLETED",
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "scores": scores,
                }
            ),
        )
        logger.info("RAGAS background evaluation completed successfully.")
    except Exception as e:
        await app_redis.set(
            "corpus:eval:status",
            json.dumps(
                {
                    "status": "FAILED",
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "scores": None,
                    "error": str(e),
                }
            ),
        )
        logger.error(f"RAGAS background evaluation failed: {e}", exc_info=True)


@router.post(
    "/eval/run",
    summary="Trigger RAG evaluation run",
    description="Runs RAGAS evaluation on sampled traces in the background.",
)
async def trigger_evaluation(
    request: Request,
    background_tasks: BackgroundTasks,
    sample_rate: float = 1.0,
    mode: str = "traces",
    limit: int = 10,
):
    """Trigger background evaluation task.

    mode="traces" scores recent Langfuse traces; mode="golden" runs the full
    pipeline over the golden question set (slow, but reflects real quality).
    """
    redis_client = request.app.state.redis
    background_tasks.add_task(run_evaluation_task, redis_client, sample_rate, mode, limit)
    return {"status": "success", "message": f"Evaluation job ({mode}) triggered in background."}


@router.get(
    "/eval/history",
    summary="Evaluation score history",
    description="Returns recent evaluation runs (newest first) for trend charts.",
)
async def get_evaluation_history(request: Request, limit: int = 30):
    """Read the eval trend history list from Redis."""
    redis_client = request.app.state.redis
    try:
        raw = await redis_client.lrange("corpus:eval:history", 0, max(0, limit - 1))
        entries = [json.loads(item) for item in raw]
    except Exception as e:
        logger.warning(f"Failed to read eval history: {e}")
        entries = []
    return {"history": entries}


@router.get(
    "/eval/status",
    summary="Get RAG evaluation status",
    description="Returns the status and metrics scores of the latest RAGAS evaluation job.",
)
async def get_evaluation_status(request: Request):
    """Retrieve evaluation status and scores from Redis."""
    redis_client = request.app.state.redis
    raw_status = await redis_client.get("corpus:eval:status")

    if not raw_status:
        # Honest status: no run has happened, so there are no scores to show.
        return {
            "status": "NOT_RUN",
            "timestamp": None,
            "scores": None,
        }

    return json.loads(raw_status)


@router.get(
    "/diagnostics/langfuse",
    summary="Get Langfuse tracing status",
    description="Checks whether Langfuse public and secret keys are configured in environment.",
)
async def get_langfuse_status():
    """Check Langfuse configuration diagnostics."""
    settings = get_settings()
    is_configured = bool(settings.langfuse.public_key and settings.langfuse.secret_key)
    return {
        "status": "CONNECTED" if is_configured else "INACTIVE",
        "public_key_configured": bool(settings.langfuse.public_key),
        "secret_key_configured": bool(settings.langfuse.secret_key),
        "host": settings.langfuse.host,
    }
