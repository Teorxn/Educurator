"""
HU-17: Historial de cambios   → GET /api/docs/{id}/history
HU-18: Métricas del sistema   → GET /api/analytics
HU-02: Gestión de usuarios    → GET/POST /api/users  (admin only)
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
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
    SuggestionType,
    User,
    UserRole,
)
from app.schemas.suggestions import AnalyticsResponse, DocumentHistoryEntry
from app.utils.security import hash_password
from pydantic import BaseModel, EmailStr

router = APIRouter(tags=["analytics & admin"])


# ── HU-17: GET /api/docs/{id}/history ───────────────────────────────────────


@router.get("/api/docs/{doc_id}/history", response_model=list[DocumentHistoryEntry])
async def get_doc_history(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(DocumentHistory)
        .where(DocumentHistory.doc_id == doc_id)
        .order_by(DocumentHistory.timestamp.desc())
    )
    return list(result.scalars().all())


# ── HU-18: GET /api/analytics ────────────────────────────────────────────────


@router.get("/api/analytics", response_model=AnalyticsResponse)
async def get_analytics(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    # Document counts by status
    doc_rows = (await db.execute(
        select(Document.status, func.count()).group_by(Document.status)
    )).all()
    by_status = {r[0].value: r[1] for r in doc_rows}
    total_docs = sum(by_status.values())

    # Suggestion counts
    sug_status_rows = (await db.execute(
        select(Suggestion.status, func.count()).group_by(Suggestion.status)
    )).all()
    sug_by_status = {r[0].value: r[1] for r in sug_status_rows}
    total_sug = sum(sug_by_status.values())

    sug_type_rows = (await db.execute(
        select(Suggestion.type, func.count()).group_by(Suggestion.type)
    )).all()
    sug_by_type = {r[0].value: r[1] for r in sug_type_rows}

    approved = sug_by_status.get("approved", 0)
    reviewed = approved + sug_by_status.get("rejected", 0)
    approval_rate = round(approved / reviewed, 4) if reviewed > 0 else 0.0

    return AnalyticsResponse(
        total_documents=total_docs,
        by_status=by_status,
        total_suggestions=total_sug,
        suggestions_by_status=sug_by_status,
        suggestions_by_type=sug_by_type,
        approval_rate=approval_rate,
    )


# ── HU-02: User management (admin only) ──────────────────────────────────────


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str
    role: UserRole = UserRole.instructor


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: UserRole
    is_active: bool

    model_config = {"from_attributes": True}


@router.get("/api/users", response_model=list[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(UserRole.admin)),
):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return list(result.scalars().all())


@router.post("/api/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(UserRole.admin)),
):
    existing = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/api/users/{user_id}/role", response_model=UserResponse)
async def update_user_role(
    user_id: uuid.UUID,
    body: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_role(UserRole.admin)),
):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    old_role = user.role
    user.role = body.role
    await db.commit()
    await db.refresh(user)

    # Audit trail for role change
    history = DocumentHistory(
        doc_id=user_id,   # reusing doc_id as generic entity_id — ok for MVP
        action=f"role_changed:{old_role.value}→{body.role.value}",
        performed_by=current_admin.id,
    )
    db.add(history)
    await db.commit()
    return user
