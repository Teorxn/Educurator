"""Service for recording document history (audit trail)."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import DocumentHistory


async def record_document_history(
    db: AsyncSession,
    *,
    doc_id: uuid.UUID | None,
    action: str,
    performed_by: uuid.UUID | None,
    before_content: dict | None = None,
    after_content: dict | None = None,
    reason: str | None = None,
) -> DocumentHistory:
    """Create an immutable audit entry for a document change.

    This function only INSERTs — history is never updated or deleted.
    The caller is responsible for committing the transaction.
    """
    entry = DocumentHistory(
        doc_id=doc_id,
        action=action,
        performed_by=performed_by,
        before_content=before_content,
        after_content=after_content,
        reason=reason,
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return entry


async def get_document_history(
    db: AsyncSession,
    doc_id: uuid.UUID,
    page: int = 1,
    limit: int = 20,
) -> tuple[list[DocumentHistory], int]:
    """Return paginated history for a document, ordered chronologically (oldest first)."""
    count_q = (
        select(func.count())
        .select_from(DocumentHistory)
        .where(DocumentHistory.doc_id == doc_id)
    )
    total = (await db.execute(count_q)).scalar_one()

    query = (
        select(DocumentHistory)
        .where(DocumentHistory.doc_id == doc_id)
        .order_by(DocumentHistory.timestamp.asc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    items = (await db.execute(query)).scalars().all()
    return list(items), total
