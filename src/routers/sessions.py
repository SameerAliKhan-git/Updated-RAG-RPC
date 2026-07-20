"""Corpus — durable chat session history (UI store; LLM memory stays in Redis)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.dependencies import get_db_session
from src.middleware.auth import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["sessions"],
    dependencies=[Depends(verify_api_key)],
)


class SessionCreate(BaseModel):
    id: str | None = None  # client may supply the session UUID used for Redis continuity
    title: str = Field(default="New chat", max_length=200)
    collection_id: str | None = None


class SessionUpdate(BaseModel):
    title: str | None = Field(None, max_length=200)
    collection_id: str | None = None


class MessageIn(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str
    citations: list[dict[str, Any]] | None = None
    meta: dict[str, Any] | None = None
    client_msg_id: str | None = None


def _session_dict(s, message_count: int | None = None) -> dict:
    d = {
        "id": str(s.id),
        "title": s.title,
        "collection_id": str(s.collection_id) if s.collection_id else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }
    if message_count is not None:
        d["message_count"] = message_count
    return d


@router.get("/sessions", summary="List chat sessions")
async def list_sessions(limit: int = 50, db=Depends(get_db_session)):
    from src.models.paper import ChatSessionRecord

    sessions = db.query(ChatSessionRecord).order_by(ChatSessionRecord.updated_at.desc()).limit(min(limit, 200)).all()
    return {"sessions": [_session_dict(s) for s in sessions]}


@router.post("/sessions", summary="Create (or idempotently ensure) a session")
async def create_session(body: SessionCreate, db=Depends(get_db_session)):
    from src.models.paper import ChatSessionRecord

    if body.id:
        existing = db.query(ChatSessionRecord).filter(ChatSessionRecord.id == body.id).first()
        if existing:
            return _session_dict(existing)

    session = ChatSessionRecord(title=body.title, collection_id=body.collection_id or None)
    if body.id:
        session.id = body.id
    db.add(session)
    db.commit()
    db.refresh(session)
    return _session_dict(session)


@router.patch("/sessions/{session_id}", summary="Rename or re-scope a session")
async def update_session(session_id: str, body: SessionUpdate, db=Depends(get_db_session)):
    from src.models.paper import ChatSessionRecord

    session = db.query(ChatSessionRecord).filter(ChatSessionRecord.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    if body.title:
        session.title = body.title
    if body.collection_id is not None:
        session.collection_id = body.collection_id or None
    db.commit()
    db.refresh(session)
    return _session_dict(session)


@router.delete("/sessions/{session_id}", summary="Delete a session and its messages")
async def delete_session(session_id: str, db=Depends(get_db_session)):
    from src.models.paper import ChatSessionRecord

    session = db.query(ChatSessionRecord).filter(ChatSessionRecord.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    db.delete(session)
    db.commit()
    return {"status": "deleted"}


@router.get("/sessions/{session_id}/messages", summary="Load a session's messages")
async def list_messages(session_id: str, db=Depends(get_db_session)):
    from src.models.paper import ChatMessageRecord

    messages = (
        db.query(ChatMessageRecord)
        .filter(ChatMessageRecord.session_id == session_id)
        .order_by(ChatMessageRecord.created_at)
        .all()
    )
    return {
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "citations": m.citations or [],
                "meta": m.meta or {},
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ]
    }


@router.post("/sessions/{session_id}/messages", summary="Append messages (bulk, idempotent)")
async def append_messages(session_id: str, body: list[MessageIn], db=Depends(get_db_session)):
    from src.models.paper import ChatMessageRecord, ChatSessionRecord

    session = db.query(ChatSessionRecord).filter(ChatSessionRecord.id == session_id).first()
    if not session:
        # Auto-create so streaming clients can persist without a prior POST /sessions
        session = ChatSessionRecord(id=session_id, title="New chat")
        db.add(session)
        db.commit()

    stored = 0
    for msg in body:
        if msg.client_msg_id:
            dup = (
                db.query(ChatMessageRecord)
                .filter(
                    ChatMessageRecord.session_id == session_id,
                    ChatMessageRecord.client_msg_id == msg.client_msg_id,
                )
                .first()
            )
            if dup:
                continue
        db.add(
            ChatMessageRecord(
                session_id=session_id,
                role=msg.role,
                content=msg.content,
                citations=msg.citations,
                meta=msg.meta,
                client_msg_id=msg.client_msg_id,
            )
        )
        stored += 1

    # First user message names the session
    if session.title == "New chat":
        first_user = next((m for m in body if m.role == "user"), None)
        if first_user:
            session.title = first_user.content[:60] + ("…" if len(first_user.content) > 60 else "")

    db.commit()
    return {"stored": stored, "skipped": len(body) - stored}
