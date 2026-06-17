import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.models import DocumentStatus


class DocumentResponse(BaseModel):
    id: uuid.UUID
    filename: str
    file_type: str
    status: DocumentStatus
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


class PatchDocumentRequest(BaseModel):
    status: DocumentStatus | None = None
    reason: str | None = None
