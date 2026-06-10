import re
import uuid
from pathlib import Path

import filetype
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.config import settings
from app.database import get_db
from app.models.models import Document, DocumentStatus, User
from app.schemas.docs import (
    CreateDocumentRequest,
    DocsListResponse,
    DocumentResponse,
    PatchDocumentRequest,
)

router = APIRouter(prefix="/api/docs", tags=["documents"])

# Allowed MIME types → file extension
ALLOWED_MIMES: dict[str, str] = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
}


def _sanitize_filename(name: str) -> str:
    name = Path(name).name                     # strip any path components
    name = re.sub(r"[^\w\s.\-]", "", name)    # keep only safe chars
    name = name.strip() or "document"
    return name


# ── POST /api/docs ──────────────────────────────────────────────────────────


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_doc(
    body: CreateDocumentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = Document(
        filename=body.filename,
        original_filename=body.filename,
        file_type=body.file_type,
        file_path="",
        size_bytes=0,
        status=DocumentStatus.needs_review,
        uploaded_by=current_user.id,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc


# ── GET /api/docs ───────────────────────────────────────────────────────────


@router.get("", response_model=DocsListResponse)
async def list_docs(
    status_filter: str | None = Query(None, alias="status"),
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

    total = (await db.execute(count_q)).scalar_one()
    docs = (await db.execute(query.offset((page - 1) * limit).limit(limit))).scalars().all()

    return DocsListResponse(items=list(docs), total=total)


# ── GET /api/docs/{id} ──────────────────────────────────────────────────────


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_doc(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


# ── PATCH /api/docs/{id} ────────────────────────────────────────────────────


@router.patch("/{doc_id}", response_model=DocumentResponse)
async def patch_doc(
    doc_id: uuid.UUID,
    body: PatchDocumentRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if body.status is not None:
        doc.status = body.status

    await db.commit()
    await db.refresh(doc)
    return doc


# ── POST /api/docs/upload ───────────────────────────────────────────────────


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_doc(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    content = await file.read()

    # Size check
    if len(content) > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds 50 MB limit",
        )

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
                detail="Only PDF, DOCX and TXT files are accepted",
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

    # DB record
    doc = Document(
        filename=safe_name,
        original_filename=file.filename or safe_name,
        file_type=file_ext,
        file_path=str(file_path),
        size_bytes=len(content),
        status=DocumentStatus.needs_review,
        uploaded_by=current_user.id,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc
