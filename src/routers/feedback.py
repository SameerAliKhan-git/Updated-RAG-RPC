"""Corpus — Feedback Router.

Enables collecting user feedback (thumbs up/down, corrections)
which can be stored in the SoR database and linked back to Langfuse traces.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.dependencies import get_db_session
from src.middleware.auth import verify_api_key
from src.models.paper import Feedback
from src.schemas.ask import FeedbackRequest

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1",
    tags=["feedback"],
    dependencies=[Depends(verify_api_key)],
)


@router.post(
    "/feedback",
    summary="Submit user feedback",
    description="Logs thumbs up/down and optional textual corrections. Links to a query and optional Langfuse trace.",
)
async def submit_feedback(
    body: FeedbackRequest,
    db_session: Session = Depends(get_db_session),
):
    """Save user feedback to Postgres."""
    try:
        feedback_entry = Feedback(
            query_id=body.query_id,
            rating=body.rating,
            correction=body.correction,
            trace_id=body.trace_id,
        )
        db_session.add(feedback_entry)
        db_session.commit()
        logger.info(
            "feedback.submitted",
            query_id=body.query_id,
            rating=body.rating,
            trace_id=body.trace_id,
        )
        return {"status": "success", "message": "Feedback submitted successfully."}
    except Exception as e:
        db_session.rollback()
        logger.error(f"Failed to submit feedback: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Database write failure.")
