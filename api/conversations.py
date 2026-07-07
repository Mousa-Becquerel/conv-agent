"""Conversation CRUD endpoints — list / get / patch / delete.

All scoped to the authenticated user via `current_user_required`. Trying to
access another user's conversation returns 404 (not 403) to avoid leaking
the existence of conversations the caller has no business knowing about.

Conversation creation is implicit: it happens inside POST /chat or
/chat/stream when the client omits `conversation_id` — no separate
POST endpoint is exposed here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from auth.deps import current_user_required
from db import get_db
from db.models import Conversation, Message, User


router = APIRouter(prefix="/conversations", tags=["Conversations"])


# ---------- Response shapes ----------
class ConversationSummary(BaseModel):
    id: str
    title: str
    doc_filter: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    payload: Optional[dict[str, Any]] = None
    created_at: datetime


class ConversationDetail(ConversationSummary):
    messages: List[MessageOut]


class ConversationPatch(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    # Empty string is treated as "clear the filter". Null means "leave alone".
    doc_filter: Optional[str] = Field(default=None, max_length=100)


def _summary(c: Conversation) -> ConversationSummary:
    return ConversationSummary(
        id=str(c.id),
        title=c.title,
        doc_filter=c.doc_filter,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


# ---------- GET / (list) ----------
@router.get("", response_model=List[ConversationSummary])
def list_conversations(
    user: User = Depends(current_user_required),
    db: Session = Depends(get_db),
) -> List[ConversationSummary]:
    rows = db.execute(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(desc(Conversation.updated_at))
    ).scalars().all()
    return [_summary(c) for c in rows]


# ---------- GET /{id} (detail with messages) ----------
@router.get("/{conv_id}", response_model=ConversationDetail)
def get_conversation(
    conv_id: UUID,
    user: User = Depends(current_user_required),
    db: Session = Depends(get_db),
) -> ConversationDetail:
    conv = db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="conversation not found")

    rows = db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at)
    ).scalars().all()

    s = _summary(conv)
    return ConversationDetail(
        **s.model_dump(),
        messages=[
            MessageOut(
                id=str(m.id),
                role=m.role,
                content=m.content,
                payload=m.payload,
                created_at=m.created_at,
            )
            for m in rows
        ],
    )


# ---------- PATCH /{id} (rename + change filter) ----------
@router.patch("/{conv_id}", response_model=ConversationSummary)
def patch_conversation(
    conv_id: UUID,
    patch: ConversationPatch,
    user: User = Depends(current_user_required),
    db: Session = Depends(get_db),
) -> ConversationSummary:
    conv = db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="conversation not found")

    if patch.title is not None:
        conv.title = patch.title or "Nuova conversazione"
    if patch.doc_filter is not None:
        # Empty string → clear filter; otherwise set it
        conv.doc_filter = patch.doc_filter or None

    db.commit()
    db.refresh(conv)
    return _summary(conv)


# ---------- DELETE /{id} ----------
@router.delete("/{conv_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_conversation(
    conv_id: UUID,
    user: User = Depends(current_user_required),
    db: Session = Depends(get_db),
) -> Response:
    conv = db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="conversation not found")

    # ON DELETE CASCADE handles messages; qa_log rows have ON DELETE SET NULL
    # on conversation_id so audit history survives the deletion.
    db.delete(conv)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
