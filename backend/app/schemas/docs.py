import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.models import DocumentCategory, DocumentStatus


class DocumentResponse(BaseModel):
    id: uuid.UUID
    filename: str
    original_filename: str | None = None
    file_type: str
    status: DocumentStatus
    category: DocumentCategory = DocumentCategory.curated
    size_bytes: int
    uploaded_at: datetime
    # HU-23 — descripción del fallo cuando status == error
    error_message: str | None = None
    # HU-25 — metadatos del documento
    uploaded_by: uuid.UUID | None = None

    model_config = {"from_attributes": True}


class DocsListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int


# ── HU-22: carga múltiple ────────────────────────────────────────────────────


class BatchUploadError(BaseModel):
    """Archivo rechazado en una carga múltiple (no cancela a los demás)."""

    filename: str
    error: str


class BatchUploadResponse(BaseModel):
    uploaded: list[DocumentResponse]
    failed: list[BatchUploadError]
    total_received: int
    total_queued: int


# ── HU-23: estado de procesamiento ───────────────────────────────────────────


class DocStatusEntry(BaseModel):
    id: uuid.UUID
    filename: str
    status: DocumentStatus
    error_message: str | None = None
    suggestions_count: int = 0


class DocsStatusResponse(BaseModel):
    """Estados para polling ligero; is_final indica si ya no hay que refrescar."""

    items: list[DocStatusEntry]
    queue_size: int = 0
    all_final: bool = True


# ── HU-25: metadatos ampliados del documento ─────────────────────────────────


class DocumentDetailResponse(DocumentResponse):
    uploader_email: str | None = None
    chunks_count: int = 0
    suggestions_count: int = 0
    pending_suggestions: int = 0


class DocumentHistoryResponse(BaseModel):
    id: uuid.UUID
    doc_id: uuid.UUID | None
    action: str
    performed_by: uuid.UUID | None
    before_content: dict | None
    after_content: dict | None
    reason: str | None
    timestamp: datetime

    model_config = {"from_attributes": True}


class DocHistoryListResponse(BaseModel):
    items: list[DocumentHistoryResponse]
    total: int


class ChunkResponse(BaseModel):
    chunk_index: int
    content: str
    token_count: int
    page_number: int | None = None


class DocContentResponse(BaseModel):
    id: uuid.UUID
    filename: str
    original_filename: str
    file_type: str
    status: DocumentStatus
    category: DocumentCategory = DocumentCategory.curated
    size_bytes: int
    uploaded_at: datetime
    updated_at: datetime | None = None
    content: str = ""
    chunks: list[ChunkResponse] = []

    model_config = {"from_attributes": True}


class PatchDocumentRequest(BaseModel):
    status: DocumentStatus | None = None
    reason: str | None = None


class DocDeleteResponse(BaseModel):
    status: str
    message: str
