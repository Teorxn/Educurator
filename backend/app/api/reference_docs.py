"""
Issue #61 — Documentos de Referencia.

Endpoints para gestionar documentos de referencia:
  - POST /api/reference-docs/upload   — Subir documento como referencia
  - GET  /api/reference-docs          — Listar referencias con paginación
  - DELETE /api/reference-docs/{id}   — Eliminar referencia y sus chunks
  - POST /api/reference-docs/process  — Reprocesar manualmente referencias pendientes
"""

import logging
import re
import uuid
from pathlib import Path

import filetype
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, require_role
from app.config import settings
from app.database import get_db
from app.models.models import (
    Document,
    DocumentCategory,
    DocumentChunk,
    DocumentStatus,
    User,
    UserRole,
)
from app.schemas.reference_docs import (
    ReferenceDocDeleteResponse,
    ReferenceDocProcessResponse,
    ReferenceDocResponse,
    ReferenceDocsListResponse,
)
from app.services.history import record_document_history
from app.services.reference_docs import (
    delete_reference_chunks,
    process_all_pending_references,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reference-docs", tags=["reference-docs"])

ALLOWED_MIMES: dict[str, str] = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
}


def _sanitize_filename(name: str) -> str:
    name = Path(name).name
    name = re.sub(r"[^\w\s.\-]", "", name)
    name = name.strip() or "document"
    return name


# ── POST /api/reference-docs/upload ────────────────────────────────────────────


@router.post(
    "/upload",
    response_model=ReferenceDocResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_reference_doc(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.instructor, UserRole.admin)),
):
    """Sube un documento como referencia (category=reference).

    El documento se guarda en REFERENCE_DOCS_DIR y se crea el registro
    en la BD con status=needs_review. Luego debe procesarse vía
    POST /api/reference-docs/process o automáticamente en segundo plano.
    """
    content = await file.read()

    # Size check
    if len(content) > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds 50 MB limit",
        )

    # MIME validation
    detected = filetype.guess(content)
    detected_mime = detected.mime if detected else (file.content_type or "")

    if detected_mime not in ALLOWED_MIMES:
        if file.content_type == "text/plain" or (file.filename or "").endswith(".txt"):
            detected_mime = "text/plain"
        else:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Only PDF, DOCX and TXT files are accepted",
            )

    file_ext = ALLOWED_MIMES[detected_mime]
    safe_name = _sanitize_filename(file.filename or "document")

    if not safe_name.lower().endswith(f".{file_ext}"):
        safe_name = f"{safe_name}.{file_ext}"

    # Persist to disk in REFERENCE_DOCS_DIR
    ref_dir = Path(settings.REFERENCE_DOCS_DIR)
    ref_dir.mkdir(parents=True, exist_ok=True)

    unique_name = f"{uuid.uuid4()}_{safe_name}"
    file_path = ref_dir / unique_name
    file_path.write_bytes(content)

    # DB record
    doc = Document(
        filename=safe_name,
        original_filename=file.filename or safe_name,
        file_type=file_ext,
        file_path=str(file_path),
        size_bytes=len(content),
        status=DocumentStatus.needs_review,
        category=DocumentCategory.reference,
        uploaded_by=current_user.id,
    )
    db.add(doc)
    await db.flush()

    # Record audit trail
    await record_document_history(
        db,
        doc_id=doc.id,
        action="reference_uploaded",
        performed_by=current_user.id,
        after_content={
            "filename": doc.filename,
            "file_type": doc.file_type,
            "size_bytes": doc.size_bytes,
            "category": doc.category.value,
            "status": doc.status.value,
        },
        reason="Documento de referencia subido",
    )

    await db.commit()
    await db.refresh(doc)
    return doc


# ── GET /api/reference-docs ────────────────────────────────────────────────────


@router.get("", response_model=ReferenceDocsListResponse)
async def list_reference_docs(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = (
        select(Document)
        .where(Document.category == DocumentCategory.reference)
        .order_by(Document.uploaded_at.desc())
    )
    count_q = (
        select(func.count())
        .select_from(Document)
        .where(Document.category == DocumentCategory.reference)
    )

    total = (await db.execute(count_q)).scalar_one()
    docs = (
        (await db.execute(query.offset((page - 1) * limit).limit(limit)))
        .scalars()
        .all()
    )

    items = [ReferenceDocResponse.model_validate(d) for d in docs]
    return ReferenceDocsListResponse(items=items, total=total)


# ── GET /api/reference-docs/{id} ────────────────────────────────────────────────


@router.get("/{doc_id}", response_model=ReferenceDocResponse)
async def get_reference_doc(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    doc = (
        await db.execute(
            select(Document).where(
                Document.id == doc_id,
                Document.category == DocumentCategory.reference,
            )
        )
    ).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Reference document not found")
    return doc


# ── DELETE /api/reference-docs/{id} ─────────────────────────────────────────────


@router.delete("/{doc_id}", response_model=ReferenceDocDeleteResponse)
async def delete_reference_doc(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.instructor, UserRole.admin)),
):
    doc = (
        await db.execute(
            select(Document).where(
                Document.id == doc_id,
                Document.category == DocumentCategory.reference,
            )
        )
    ).scalar_one_or_none()

    if not doc:
        raise HTTPException(status_code=404, detail="Reference document not found")

    # Get chroma_ids to delete from vector store
    chunks_result = await db.execute(
        select(DocumentChunk).where(DocumentChunk.document_id == doc_id)
    )
    chunks = list(chunks_result.scalars().all())
    chroma_ids = [c.chroma_id for c in chunks if c.chroma_id]

    # Delete file from disk
    file_path = Path(doc.file_path)
    if file_path.exists():
        file_path.unlink()

    # Delete from ChromaDB
    if chroma_ids:
        await delete_reference_chunks(doc_id, chroma_ids)

    # Record audit trail before deletion
    await record_document_history(
        db,
        doc_id=doc.id,
        action="reference_deleted",
        performed_by=current_user.id,
        before_content={
            "filename": doc.filename,
            "size_bytes": doc.size_bytes,
            "status": doc.status.value,
            "chunks_count": len(chunks),
        },
        reason="Documento de referencia eliminado",
    )

    # Delete chunks from Postgres
    for chunk in chunks:
        await db.delete(chunk)

    # Delete document record
    await db.delete(doc)
    await db.commit()

    logger.info("🗑️  Referencia %s eliminada por usuario %s", doc_id, current_user.id)

    return ReferenceDocDeleteResponse(
        status="success",
        message="Reference document deleted successfully",
    )


# ── POST /api/reference-docs/process ────────────────────────────────────────────


@router.post("/process", response_model=list[ReferenceDocProcessResponse])
async def process_references(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.instructor, UserRole.admin)),
):
    """Procesa (o reprocesa) documentos de referencia pendientes.

    Busca documentos reference con status=needs_review o processing
    y ejecuta el pipeline: parse → chunk → embed → mark approved.
    NO genera sugerencias.
    """
    results = await process_all_pending_references()

    # Record audit trail for processed documents
    for r in results:
        if r.get("status") == "success" and r.get("doc_id"):
            try:
                await record_document_history(
                    db,
                    doc_id=uuid.UUID(r["doc_id"]),
                    action="reference_processed",
                    performed_by=current_user.id,
                    after_content={
                        "chunks_count": r.get("chunks_count"),
                    },
                    reason="Documento de referencia procesado",
                )
            except Exception as e:
                logger.warning(
                    "No se pudo registrar historial para %s: %s",
                    r.get("doc_id"),
                    e,
                )

    await db.commit()

    return [
        ReferenceDocProcessResponse(
            status=r.get("status", "error"),
            doc_id=r.get("doc_id"),
            chunks_count=r.get("chunks_count"),
            error=r.get("error"),
        )
        for r in results
    ]
