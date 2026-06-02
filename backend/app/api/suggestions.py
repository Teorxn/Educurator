"""
Épica 4 — Gestión de Sugerencias
HU-09: Consultar sugerencias
HU-11: Aprobar sugerencias
HU-12: Rechazar sugerencias
HU-14: Revisar FAQs (mismo flujo, type=faq)
HU-15: Proporcionar retroalimentación
"""
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.database import get_db
from app.models.models import (
    DocumentHistory,
    FeedbackPattern,
    Suggestion,
    SuggestionStatus,
    SuggestionType,
    User,
)
from app.schemas.suggestions import (
    FeedbackRequest,
    RejectRequest,
    SuggestionResponse,
    SuggestionsListResponse,
)

router = APIRouter(prefix="/api/suggestions", tags=["suggestions"])


# ── GET /api/suggestions ─────────────────────────────────────────────────────


@router.get("", response_model=SuggestionsListResponse)
async def list_suggestions(
    status_filter: str | None = Query(None, alias="status"),
    type_filter: str | None = Query(None, alias="type"),
    doc_id: uuid.UUID | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = select(Suggestion).order_by(Suggestion.created_at.desc())
    count_q = select(func.count()).select_from(Suggestion)

    if status_filter:
        try:
            s = SuggestionStatus(status_filter)
            query = query.where(Suggestion.status == s)
            count_q = count_q.where(Suggestion.status == s)
        except ValueError:
            pass

    if type_filter:
        try:
            t = SuggestionType(type_filter)
            query = query.where(Suggestion.type == t)
            count_q = count_q.where(Suggestion.type == t)
        except ValueError:
            pass

    if doc_id:
        query = query.where(Suggestion.doc_id == doc_id)
        count_q = count_q.where(Suggestion.doc_id == doc_id)

    total = (await db.execute(count_q)).scalar_one()
    items = (await db.execute(query.offset((page - 1) * limit).limit(limit))).scalars().all()

    return SuggestionsListResponse(items=list(items), total=total)


# ── GET /api/suggestions/{id} ────────────────────────────────────────────────


@router.get("/{suggestion_id}", response_model=SuggestionResponse)
async def get_suggestion(
    suggestion_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    s = (await db.execute(select(Suggestion).where(Suggestion.id == suggestion_id))).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return s


# ── POST /api/suggestions/{id}/approve ───────────────────────────────────────


@router.post("/{suggestion_id}/approve", response_model=SuggestionResponse)
async def approve_suggestion(
    suggestion_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = (await db.execute(select(Suggestion).where(Suggestion.id == suggestion_id))).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if s.status != SuggestionStatus.pending:
        raise HTTPException(status_code=400, detail="Only pending suggestions can be approved")

    s.status = SuggestionStatus.approved
    s.reviewed_by = current_user.id
    s.reviewed_at = datetime.now(timezone.utc)

    # Audit trail — HU-17
    history = DocumentHistory(
        doc_id=s.doc_id,
        action="suggestion_approved",
        performed_by=current_user.id,
        before_state=json.dumps({"suggestion_status": "pending"}),
        after_state=json.dumps({"suggestion_status": "approved", "suggestion_id": str(s.id)}),
    )
    db.add(history)

    # Feedback pattern — HU-15/16
    pattern = FeedbackPattern(
        suggestion_id=s.id,
        feedback_type="approve",
        context=json.dumps({"suggestion_type": s.type.value, "doc_id": str(s.doc_id)}),
    )
    db.add(pattern)

    await db.commit()
    await db.refresh(s)
    return s


# ── POST /api/suggestions/{id}/reject ────────────────────────────────────────


@router.post("/{suggestion_id}/reject", response_model=SuggestionResponse)
async def reject_suggestion(
    suggestion_id: uuid.UUID,
    body: RejectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = (await db.execute(select(Suggestion).where(Suggestion.id == suggestion_id))).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if s.status != SuggestionStatus.pending:
        raise HTTPException(status_code=400, detail="Only pending suggestions can be rejected")

    s.status = SuggestionStatus.rejected
    s.rejection_reason = body.reason
    s.reviewed_by = current_user.id
    s.reviewed_at = datetime.now(timezone.utc)

    # Audit trail — HU-17
    history = DocumentHistory(
        doc_id=s.doc_id,
        action="suggestion_rejected",
        performed_by=current_user.id,
        reason=body.reason,
        before_state=json.dumps({"suggestion_status": "pending"}),
        after_state=json.dumps({"suggestion_status": "rejected", "reason": body.reason}),
    )
    db.add(history)

    # Feedback pattern — HU-15/16
    pattern = FeedbackPattern(
        suggestion_id=s.id,
        feedback_type="reject",
        comment=body.reason,
        context=json.dumps({"suggestion_type": s.type.value, "doc_id": str(s.doc_id)}),
    )
    db.add(pattern)

    await db.commit()
    await db.refresh(s)
    return s


# ── POST /api/suggestions/{id}/feedback ──────────────────────────────────────


@router.post("/{suggestion_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def add_feedback(
    suggestion_id: uuid.UUID,
    body: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = (await db.execute(select(Suggestion).where(Suggestion.id == suggestion_id))).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    pattern = FeedbackPattern(
        suggestion_id=s.id,
        feedback_type=s.status.value,
        comment=body.comment,
        context=json.dumps({"suggestion_type": s.type.value, "user_id": str(current_user.id)}),
    )
    db.add(pattern)
    await db.commit()
