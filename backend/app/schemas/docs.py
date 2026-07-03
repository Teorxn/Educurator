import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.models import DocumentCategory, DocumentStatus


class DocumentResponse(BaseModel):
    id: uuid.UUID
    filename: str
    file_type: str
    status: DocumentStatus
    category: DocumentCategory = DocumentCategory.curated
    size_bytes: int
    uploaded_at: datetime

    model_config = {"from_attributes": True}


class DocsListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int


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
