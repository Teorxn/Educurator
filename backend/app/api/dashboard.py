"""
HU-20 — Visualizar un panel de inicio (resumen agregado)
HU-32 — Consultar el consumo de tokens

Ambos endpoints agregan datos en una sola llamada para que el frontend
no encadene round-trips (HU-20 exige carga < 3 s).
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.config import settings
from app.database import get_db
from app.models.models import (
    AgentRun,
    Document,
    DocumentStatus,
    Suggestion,
    SuggestionStatus,
    TokenUsage,
    User,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["dashboard"])


# ── HU-20: GET /api/analytics/dashboard ──────────────────────────────────────


@router.get("/dashboard")
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Resumen del panel de inicio: recientes, pendientes y métricas."""
    # Últimos 5 documentos procesados
    recent_rows = (
        await db.execute(
            select(
                Document.id,
                Document.filename,
                Document.status,
                Document.uploaded_at,
                func.count(Suggestion.id),
            )
            .outerjoin(Suggestion, Suggestion.document_id == Document.id)
            .group_by(
                Document.id,
                Document.filename,
                Document.status,
                Document.uploaded_at,
            )
            .order_by(Document.uploaded_at.desc())
            .limit(5)
        )
    ).all()

    # Documentos pendientes de revisión, con acceso directo desde el panel
    pending_states = (DocumentStatus.needs_review, DocumentStatus.analyzed)
    pending_rows = (
        await db.execute(
            select(
                Document.id,
                Document.filename,
                Document.status,
                func.count(Suggestion.id),
            )
            .outerjoin(
                Suggestion,
                (Suggestion.document_id == Document.id)
                & (Suggestion.status == SuggestionStatus.pending),
            )
            .where(Document.status.in_(pending_states))
            .group_by(Document.id, Document.filename, Document.status)
            .order_by(Document.uploaded_at.desc())
            .limit(10)
        )
    ).all()

    # Métricas generales
    total_docs = (
        await db.execute(select(func.count()).select_from(Document))
    ).scalar_one()
    sug_rows = (
        await db.execute(
            select(Suggestion.status, func.count()).group_by(Suggestion.status)
        )
    ).all()
    sug_by_status = {r[0].value: r[1] for r in sug_rows}
    total_sug = sum(sug_by_status.values())
    approved = sug_by_status.get("approved", 0)
    reviewed = approved + sug_by_status.get("rejected", 0)
    approval_rate = round(approved / reviewed, 4) if reviewed else 0.0

    last_run = (
        await db.execute(
            select(AgentRun).order_by(AgentRun.started_at.desc()).limit(1)
        )
    ).scalar_one_or_none()

    return {
        "recent_documents": [
            {
                "id": str(r[0]),
                "filename": r[1],
                "status": r[2].value if hasattr(r[2], "value") else r[2],
                "uploaded_at": r[3].isoformat() if r[3] else None,
                "suggestions_count": r[4] or 0,
            }
            for r in recent_rows
        ],
        "pending_documents": [
            {
                "id": str(r[0]),
                "filename": r[1],
                "status": r[2].value if hasattr(r[2], "value") else r[2],
                "pending_suggestions": r[3] or 0,
            }
            for r in pending_rows
        ],
        "metrics": {
            "total_documents": total_docs,
            "total_suggestions": total_sug,
            "pending_suggestions": sug_by_status.get("pending", 0),
            "approved_suggestions": approved,
            "rejected_suggestions": sug_by_status.get("rejected", 0),
            "approval_rate": approval_rate,
        },
        "last_run": (
            {
                "thread_id": last_run.thread_id,
                "status": (
                    last_run.status.value
                    if hasattr(last_run.status, "value")
                    else last_run.status
                ),
                "started_at": (
                    last_run.started_at.isoformat() if last_run.started_at else None
                ),
                "duration_seconds": last_run.duration_seconds,
                "suggestions_generated": last_run.suggestions_generated,
            }
            if last_run
            else None
        ),
    }


# ── HU-32: GET /api/analytics/tokens ─────────────────────────────────────────


@router.get("/tokens")
async def get_token_analytics(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Consumo de tokens y costo ESTIMADO del LLM, por operación y modelo."""
    days = max(1, min(days, 365))
    since = datetime.now(timezone.utc) - timedelta(days=days)

    totals = (
        await db.execute(
            select(
                func.coalesce(func.sum(TokenUsage.total_tokens), 0),
                func.coalesce(func.sum(TokenUsage.input_tokens), 0),
                func.coalesce(func.sum(TokenUsage.output_tokens), 0),
                func.coalesce(func.sum(TokenUsage.cost_usd), 0.0),
                func.count(),
            ).where(TokenUsage.created_at >= since)
        )
    ).one()

    by_operation_rows = (
        await db.execute(
            select(
                TokenUsage.operation,
                func.sum(TokenUsage.total_tokens),
                func.sum(TokenUsage.cost_usd),
            )
            .where(TokenUsage.created_at >= since)
            .group_by(TokenUsage.operation)
        )
    ).all()

    by_model_rows = (
        await db.execute(
            select(
                TokenUsage.model,
                func.sum(TokenUsage.total_tokens),
                func.sum(TokenUsage.cost_usd),
            )
            .where(TokenUsage.created_at >= since)
            .group_by(TokenUsage.model)
        )
    ).all()

    # Serie diaria para el gráfico de barras (últimos N días)
    daily_rows = (
        await db.execute(
            select(
                func.date(TokenUsage.created_at),
                func.sum(TokenUsage.total_tokens),
                func.sum(TokenUsage.cost_usd),
            )
            .where(TokenUsage.created_at >= since)
            .group_by(func.date(TokenUsage.created_at))
            .order_by(func.date(TokenUsage.created_at))
        )
    ).all()

    # Consumo del último análisis
    last_thread = (
        await db.execute(
            select(TokenUsage.thread_id)
            .where(TokenUsage.thread_id.isnot(None))
            .order_by(TokenUsage.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    last_run_tokens, last_run_cost = 0, 0.0
    if last_thread:
        row = (
            await db.execute(
                select(
                    func.coalesce(func.sum(TokenUsage.total_tokens), 0),
                    func.coalesce(func.sum(TokenUsage.cost_usd), 0.0),
                ).where(TokenUsage.thread_id == last_thread)
            )
        ).one()
        last_run_tokens, last_run_cost = int(row[0]), float(row[1])

    return {
        "period_days": days,
        "total_tokens": int(totals[0]),
        "input_tokens": int(totals[1]),
        "output_tokens": int(totals[2]),
        "total_cost_usd": round(float(totals[3]), 6),
        "calls": int(totals[4]),
        "last_run": {
            "thread_id": last_thread,
            "total_tokens": last_run_tokens,
            "cost_usd": round(last_run_cost, 6),
        },
        "by_operation": {
            r[0]: {"tokens": int(r[1] or 0), "cost_usd": round(float(r[2] or 0), 6)}
            for r in by_operation_rows
        },
        "by_model": {
            r[0]: {"tokens": int(r[1] or 0), "cost_usd": round(float(r[2] or 0), 6)}
            for r in by_model_rows
        },
        "daily": [
            {
                "date": str(r[0]),
                "tokens": int(r[1] or 0),
                "cost_usd": round(float(r[2] or 0), 6),
            }
            for r in daily_rows
        ],
        "rates": {
            "input_per_1k": settings.LLM_COST_PER_1K_INPUT_TOKENS,
            "output_per_1k": settings.LLM_COST_PER_1K_OUTPUT_TOKENS,
        },
        "estimated": True,
    }
