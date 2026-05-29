"""
#19 — Endpoints approve/reject + versionado documentos
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.models import (
    Document,
    DocumentHistory,
    DocumentStatus,
    Suggestion,
    SuggestionStatus,
    User,
    UserRole,
)
from app.schemas.suggestions import (
    ApproveResponse,
    RejectRequest,
    RejectResponse,
    SuggestionsListResponse,
    SuggestionResponse,
)

router = APIRouter(prefix="/api/suggestions", tags=["suggestions"])


# ── GET /api/suggestions ──────────────────────────────────────────────────────


@router.get("", response_model=SuggestionsListResponse)
async def list_suggestions(
    status_filter: str | None = Query(None, alias="status"),
    type_filter: str | None = Query(None, alias="type"),
    document_id: uuid.UUID | None = Query(None),
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
            t = type_filter
            query = query.where(Suggestion.type == t)
            count_q = count_q.where(Suggestion.type == t)
        except ValueError:
            pass

    if document_id:
        query = query.where(Suggestion.document_id == document_id)
        count_q = count_q.where(Suggestion.document_id == document_id)

    total = (await db.execute(count_q)).scalar_one()
    items = (
        await db.execute(query.offset((page - 1) * limit).limit(limit))
    ).scalars().all()

    result = []
    for s in items:
        doc = (
            await db.execute(select(Document).where(Document.id == s.document_id))
        ).scalar_one_or_none()
        resp = SuggestionResponse.model_validate(s)
        resp.document_name = doc.filename if doc else None
        result.append(resp)

    return SuggestionsListResponse(items=result, total=total)


# ── POST /api/suggestions/{id}/approve ────────────────────────────────────────


@router.post("/{suggestion_id}/approve", response_model=ApproveResponse)
async def approve_suggestion(
    suggestion_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.instructor, UserRole.admin)),
):
    suggestion = (
        await db.execute(select(Suggestion).where(Suggestion.id == suggestion_id))
    ).scalar_one_or_none()

    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    if suggestion.status != SuggestionStatus.pending:
        raise HTTPException(status_code=400, detail="Suggestion is not pending")

    old_status = suggestion.status.value
    suggestion.status = SuggestionStatus.approved
    suggestion.reviewed_by = current_user.id
    suggestion.reviewed_at = datetime.now(timezone.utc)

    doc = (
        await db.execute(select(Document).where(Document.id == suggestion.document_id))
    ).scalar_one_or_none()
    if doc:
        doc.status = DocumentStatus.approved

    history = DocumentHistory(
        doc_id=suggestion.document_id,
        action="approved",
        performed_by=current_user.id,
        before_content={"status": old_status},
        after_content={"status": "approved", "suggestion_id": str(suggestion.id)},
        reason=None,
    )
    db.add(history)
    await db.commit()
    await db.refresh(suggestion)

    return ApproveResponse(
        id=suggestion.id,
        status=suggestion.status,
        message="Sugerencia aprobada correctamente",
    )


# ── POST /api/suggestions/{id}/reject ─────────────────────────────────────────


@router.post("/{suggestion_id}/reject", response_model=RejectResponse)
async def reject_suggestion(
    suggestion_id: uuid.UUID,
    body: RejectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.instructor, UserRole.admin)),
):
    if not body.reason or not body.reason.strip():
        raise HTTPException(
            status_code=400, detail="Reason is required for rejection"
        )

    suggestion = (
        await db.execute(select(Suggestion).where(Suggestion.id == suggestion_id))
    ).scalar_one_or_none()

    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    if suggestion.status != SuggestionStatus.pending:
        raise HTTPException(status_code=400, detail="Suggestion is not pending")

    old_status = suggestion.status.value
    suggestion.status = SuggestionStatus.rejected
    suggestion.reviewed_by = current_user.id
    suggestion.review_reason = body.reason.strip()
    suggestion.reviewed_at = datetime.now(timezone.utc)

    doc = (
        await db.execute(select(Document).where(Document.id == suggestion.document_id))
    ).scalar_one_or_none()
    if doc:
        doc.status = DocumentStatus.rejected

    history = DocumentHistory(
        doc_id=suggestion.document_id,
        action="rejected",
        performed_by=current_user.id,
        before_content={"status": old_status},
        after_content={"status": "rejected", "suggestion_id": str(suggestion.id)},
        reason=body.reason.strip(),
    )
    db.add(history)
    await db.commit()
    await db.refresh(suggestion)

    return RejectResponse(
        id=suggestion.id,
        status=suggestion.status,
        message="Sugerencia rechazada",
    )
