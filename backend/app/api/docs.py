import logging
import re
import uuid
from pathlib import Path

import filetype
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, require_role
from app.config import settings
from app.database import AsyncSessionLocal, get_db
from app.models.models import (
    Document,
    DocumentCategory,
    DocumentChunk,
    DocumentHistory,
    DocumentStatus,
    FeedbackPattern,
    Suggestion,
    SuggestionStatus,
    User,
    UserRole,
)
from app.services.curation_queue import enqueue_curation, queue_size
from app.schemas.docs import (
    BatchUploadError,
    BatchUploadResponse,
    ChunkResponse,
    DocContentResponse,
    DocStatusEntry,
    DocsStatusResponse,
    DocumentDetailResponse,
    DocDeleteResponse,
    DocHistoryListResponse,
    DocsListResponse,
    DocumentHistoryResponse,
    DocumentResponse,
    PatchDocumentRequest,
)
from app.services.history import get_document_history, record_document_history

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/docs", tags=["documents"])

# Allowed MIME types → file extension
ALLOWED_MIMES: dict[str, str] = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
}


def _sanitize_filename(name: str) -> str:
    name = Path(name).name  # strip any path components
    name = re.sub(r"[^\w\s.\-]", "", name)  # keep only safe chars
    name = name.strip() or "document"
    return name


# ── GET /api/docs ───────────────────────────────────────────────────────────


@router.get("", response_model=DocsListResponse)
async def list_docs(
    status_filter: str | None = Query(None, alias="status"),
    category_filter: str | None = Query("curated", alias="category"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = select(Document).order_by(Document.uploaded_at.desc())
    count_q = select(func.count()).select_from(Document)

    if status_filter:
        try:
            s = DocumentStatus(status_filter)
            query = query.where(Document.status == s)
            count_q = count_q.where(Document.status == s)
        except ValueError:
            pass

    if category_filter and category_filter != "all":
        try:
            c = DocumentCategory(category_filter)
            query = query.where(Document.category == c)
            count_q = count_q.where(Document.category == c)
        except ValueError:
            pass

    total = (await db.execute(count_q)).scalar_one()
    docs = (
        (await db.execute(query.offset((page - 1) * limit).limit(limit)))
        .scalars()
        .all()
    )

    items = [DocumentResponse.model_validate(d) for d in docs]
    return DocsListResponse(items=items, total=total)


# ── HU-23: GET /api/docs/status/all ─────────────────────────────────────────
# IMPORTANTE: debe declararse ANTES de /{doc_id} para que 'status' no se
# interprete como un UUID de documento.


@router.get("/status/all", response_model=DocsStatusResponse)
async def get_docs_status(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Estados de procesamiento de todos los documentos (polling ligero).

    `all_final=True` significa que ningún documento sigue en cola o
    procesándose: el frontend puede detener el polling.
    """
    rows = (
        await db.execute(
            select(
                Document.id,
                Document.filename,
                Document.status,
                Document.error_message,
                func.count(Suggestion.id),
            )
            .outerjoin(Suggestion, Suggestion.document_id == Document.id)
            .group_by(
                Document.id,
                Document.filename,
                Document.status,
                Document.error_message,
            )
            .order_by(Document.uploaded_at.desc())
        )
    ).all()

    in_flight = {DocumentStatus.queued, DocumentStatus.processing}
    items = [
        DocStatusEntry(
            id=r[0],
            filename=r[1],
            status=r[2],
            error_message=r[3],
            suggestions_count=r[4] or 0,
        )
        for r in rows
    ]
    return DocsStatusResponse(
        items=items,
        queue_size=queue_size(),
        all_final=not any(i.status in in_flight for i in items),
    )


# ── GET /api/docs/{id} ──────────────────────────────────────────────────────


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_doc(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    doc = (
        await db.execute(select(Document).where(Document.id == doc_id))
    ).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


# ── GET /api/docs/{id}/content ───────────────────────────────────────────────


@router.get("/{doc_id}/content", response_model=DocContentResponse)
async def get_doc_content(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    doc = (
        await db.execute(select(Document).where(Document.id == doc_id))
    ).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Get chunks ordered by index
    chunks_q = (
        select(DocumentChunk)
        .where(DocumentChunk.document_id == doc_id)
        .order_by(DocumentChunk.chunk_index)
    )
    chunks = (await db.execute(chunks_q)).scalars().all()

    chunk_responses = [
        ChunkResponse(
            chunk_index=c.chunk_index,
            content=c.content,
            token_count=c.token_count,
            page_number=c.page_number,
        )
        for c in chunks
    ]

    # Full concatenated text
    full_text = "\n\n".join(c.content for c in chunks)

    return DocContentResponse(
        id=doc.id,
        filename=doc.filename,
        original_filename=doc.original_filename,
        file_type=doc.file_type,
        status=doc.status,
        category=doc.category,
        size_bytes=doc.size_bytes,
        uploaded_at=doc.uploaded_at,
        updated_at=doc.updated_at,
        content=full_text,
        chunks=chunk_responses,
    )


# ── GET /api/docs/{id}/history ──────────────────────────────────────────────


@router.get("/{doc_id}/history", response_model=DocHistoryListResponse)
async def get_doc_history(
    doc_id: uuid.UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    # Verify document exists
    doc = (
        await db.execute(select(Document).where(Document.id == doc_id))
    ).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    items, total = await get_document_history(db, doc_id, page=page, limit=limit)
    return DocHistoryListResponse(
        items=[DocumentHistoryResponse.model_validate(h) for h in items],
        total=total,
    )


# ── PATCH /api/docs/{id} ────────────────────────────────────────────────────


@router.patch("/{doc_id}", response_model=DocumentResponse)
async def patch_doc(
    doc_id: uuid.UUID,
    body: PatchDocumentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = (
        await db.execute(select(Document).where(Document.id == doc_id))
    ).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # HU-27 — Un documento solo puede aprobarse cuando TODAS sus sugerencias
    # fueron revisadas (aprobadas o rechazadas). Backend = fuente de verdad.
    if body.status == DocumentStatus.approved:
        pending = (
            await db.execute(
                select(func.count())
                .select_from(Suggestion)
                .where(Suggestion.document_id == doc_id)
                .where(Suggestion.status == SuggestionStatus.pending)
            )
        ).scalar_one()
        if pending > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"No puedes aprobar este documento: {pending} "
                    f"sugerencia{'s' if pending != 1 else ''} "
                    f"{'están' if pending != 1 else 'está'} pendiente"
                    f"{'s' if pending != 1 else ''} de revisión"
                ),
            )

    if body.status is not None and body.status != doc.status:
        # Snapshot before state
        before_content = {
            "status": doc.status.value,
            "updated_at": (doc.updated_at.isoformat() if doc.updated_at else None),
        }

        doc.status = body.status
        await db.flush()

        # Snapshot after state
        after_content = {
            "status": doc.status.value,
            "updated_at": (doc.updated_at.isoformat() if doc.updated_at else None),
        }

        # Record history for approve / reject / archive actions
        await record_document_history(
            db,
            doc_id=doc.id,
            action=body.status.value,  # "approved", "rejected", "archived", etc.
            performed_by=current_user.id,
            before_content=before_content,
            after_content=after_content,
            reason=body.reason,
        )
    elif body.status is not None:
        doc.status = body.status

    await db.commit()
    await db.refresh(doc)
    return doc


# ── DELETE /api/docs/{id} ────────────────────────────────────────────────────


@router.delete("/{doc_id}", response_model=DocDeleteResponse)
async def delete_doc(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = (
        await db.execute(select(Document).where(Document.id == doc_id))
    ).scalar_one_or_none()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

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
        try:
            from app.rag.embeddings import get_chroma_collection

            collection = get_chroma_collection()
            collection.delete(ids=chroma_ids)
            logger.info(
                "  🗑️  Eliminados %d chunks de ChromaDB para documento %s",
                len(chroma_ids),
                doc_id,
            )
        except Exception as e:
            logger.error(
                "  ❌ Error eliminando chunks de ChromaDB para %s: %s", doc_id, e
            )

    # Record audit trail before deletion
    await record_document_history(
        db,
        doc_id=doc.id,
        action="deleted",
        performed_by=current_user.id,
        before_content={
            "filename": doc.filename,
            "size_bytes": doc.size_bytes,
            "status": doc.status.value,
            "category": doc.category.value,
            "chunks_count": len(chunks),
        },
        reason="Documento eliminado por el usuario",
    )

    # Delete suggestions and their feedback patterns
    suggestions_list = (
        (await db.execute(select(Suggestion).where(Suggestion.document_id == doc_id)))
        .scalars()
        .all()
    )

    for sug in suggestions_list:
        feedback_q = select(FeedbackPattern).where(
            FeedbackPattern.suggestion_id == sug.id
        )
        feedbacks = (await db.execute(feedback_q)).scalars().all()
        for fb in feedbacks:
            await db.delete(fb)

        await db.delete(sug)

    # Delete chunks
    for chunk in chunks:
        await db.delete(chunk)

    # Delete history entries
    history_q = select(DocumentHistory).where(DocumentHistory.doc_id == doc_id)
    history_entries = (await db.execute(history_q)).scalars().all()
    for entry in history_entries:
        await db.delete(entry)

    # Delete document record
    await db.delete(doc)
    await db.commit()

    logger.info("🗑️  Documento %s eliminado por usuario %s", doc_id, current_user.id)

    return DocDeleteResponse(
        status="success",
        message="Document deleted successfully",
    )


# ── POST /api/docs/upload ───────────────────────────────────────────────────


@router.post(
    "/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED
)
async def upload_doc(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    """Sube un documento y lo encola para análisis automático."""
    content = await file.read()
    doc = await _persist_upload(db, file, content, current_user)
    await db.commit()
    await db.refresh(doc)

    background_tasks.add_task(enqueue_curation, str(doc.id))
    return doc


# ── HU-22: POST /api/docs/upload-batch ───────────────────────────────────────


@router.post("/upload-batch", response_model=BatchUploadResponse)
async def upload_docs_batch(
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    """Sube varios documentos a la vez (HU-22).

    Cada archivo se valida de forma individual: los inválidos se reportan
    con su mensaje de error sin cancelar los válidos. Los aceptados se
    encolan y el worker los procesa SECUENCIALMENTE para no saturar el
    pipeline RAG.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No se recibió ningún archivo")

    max_batch = getattr(settings, "MAX_BATCH_UPLOAD", 10)
    if len(files) > max_batch:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Máximo {max_batch} documentos por carga (recibidos: {len(files)})",
        )

    uploaded: list[DocumentResponse] = []
    failed: list[BatchUploadError] = []

    for f in files:
        try:
            content = await f.read()
            doc = await _persist_upload(db, f, content, current_user)
            await db.flush()
            uploaded.append(DocumentResponse.model_validate(doc))
        except HTTPException as e:
            # Un archivo inválido NO cancela los demás
            failed.append(
                BatchUploadError(filename=f.filename or "(sin nombre)", error=e.detail)
            )
        except Exception as e:
            logger.exception("Error subiendo %s", f.filename)
            failed.append(
                BatchUploadError(filename=f.filename or "(sin nombre)", error=str(e))
            )

    await db.commit()

    for d in uploaded:
        background_tasks.add_task(enqueue_curation, str(d.id))

    logger.info(
        "📤 Carga múltiple: %d aceptados, %d rechazados", len(uploaded), len(failed)
    )
    return BatchUploadResponse(
        uploaded=uploaded,
        failed=failed,
        total_received=len(files),
        total_queued=len(uploaded),
    )


async def _persist_upload(
    db: AsyncSession,
    file: UploadFile,
    content: bytes,
    current_user: User,
) -> Document:
    """Valida y persiste UN archivo. Lanza HTTPException si es inválido.

    No hace commit: el caller decide (individual o batch).
    """
    if len(content) > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"El archivo supera el límite de "
            f"{settings.MAX_FILE_SIZE // (1024 * 1024)} MB",
        )
    if not content:
        raise HTTPException(status_code=400, detail="El archivo está vacío")

    # MIME validation via content inspection (not just Content-Type header)
    detected = filetype.guess(content)
    detected_mime = detected.mime if detected else (file.content_type or "")

    # Plain text isn't detected by magic bytes — fall back to Content-Type for .txt
    if detected_mime not in ALLOWED_MIMES:
        if file.content_type == "text/plain" or (file.filename or "").endswith(".txt"):
            detected_mime = "text/plain"
        else:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Solo se aceptan archivos PDF, DOCX y TXT",
            )

    file_ext = ALLOWED_MIMES[detected_mime]
    safe_name = _sanitize_filename(file.filename or "document")
    if not safe_name.lower().endswith(f".{file_ext}"):
        safe_name = f"{safe_name}.{file_ext}"

    # Persist to disk outside web root
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    unique_name = f"{uuid.uuid4()}_{safe_name}"
    file_path = upload_dir / unique_name
    file_path.write_bytes(content)

    doc = Document(
        filename=safe_name,
        original_filename=file.filename or safe_name,
        file_type=file_ext,
        file_path=str(file_path),
        size_bytes=len(content),
        # HU-23: nace en cola; el worker lo pasa a processing → analyzed/error
        status=DocumentStatus.queued,
        uploaded_by=current_user.id,
    )
    db.add(doc)
    return doc


# ── HU-25: GET /api/docs/{id}/download — descarga del original ───────────────


@router.get("/{doc_id}/download")
async def download_doc(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Descarga el archivo original, byte a byte idéntico al subido.

    Valida que el usuario autenticado tenga acceso: los instructores solo
    descargan sus propios documentos o los de referencia (corpus común);
    los administradores acceden a todo.
    """
    doc = (
        await db.execute(select(Document).where(Document.id == doc_id))
    ).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    is_owner = doc.uploaded_by == current_user.id
    is_reference = doc.category == DocumentCategory.reference
    if current_user.role != UserRole.admin and not (is_owner or is_reference):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a este documento",
        )

    file_path = Path(doc.file_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=404, detail="El archivo ya no está disponible en el servidor"
        )

    media_types = {
        "pdf": "application/pdf",
        "docx": (
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        ),
        "txt": "text/plain; charset=utf-8",
    }
    return FileResponse(
        path=str(file_path),
        media_type=media_types.get(doc.file_type, "application/octet-stream"),
        filename=doc.original_filename or doc.filename,
    )


# ── HU-25: GET /api/docs/{id}/detail — metadatos completos ───────────────────


@router.get("/{doc_id}/detail", response_model=DocumentDetailResponse)
async def get_doc_detail(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Metadatos del documento: uploader, tamaño, estado, chunks y sugerencias."""
    doc = (
        await db.execute(select(Document).where(Document.id == doc_id))
    ).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    uploader_email = None
    if doc.uploaded_by:
        uploader_email = (
            await db.execute(select(User.email).where(User.id == doc.uploaded_by))
        ).scalar_one_or_none()

    chunks_count = (
        await db.execute(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_id == doc_id)
        )
    ).scalar_one()
    total_suggestions = (
        await db.execute(
            select(func.count())
            .select_from(Suggestion)
            .where(Suggestion.document_id == doc_id)
        )
    ).scalar_one()
    pending = (
        await db.execute(
            select(func.count())
            .select_from(Suggestion)
            .where(Suggestion.document_id == doc_id)
            .where(Suggestion.status == SuggestionStatus.pending)
        )
    ).scalar_one()

    detail = DocumentDetailResponse.model_validate(doc)
    detail.uploader_email = uploader_email
    detail.chunks_count = chunks_count or 0
    detail.suggestions_count = total_suggestions or 0
    detail.pending_suggestions = pending or 0
    return detail


# ── HU-23: POST /api/docs/{id}/retry — reintentar tras error ─────────────────


@router.post("/{doc_id}/retry", response_model=DocumentResponse)
async def retry_doc_analysis(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(UserRole.instructor, UserRole.admin)),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    """Reencola un documento cuyo análisis falló o quedó pendiente."""
    doc = (
        await db.execute(select(Document).where(Document.id == doc_id))
    ).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    if doc.status in (DocumentStatus.queued, DocumentStatus.processing):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El documento ya está en cola o procesándose",
        )

    doc.status = DocumentStatus.queued
    doc.error_message = None
    await db.commit()
    await db.refresh(doc)

    background_tasks.add_task(enqueue_curation, str(doc.id))
    return doc
