import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.models import DocumentStatus


class ReferenceDocResponse(BaseModel):
    id: uuid.UUID
    filename: str
    file_type: str
    status: DocumentStatus
    size_bytes: int
    uploaded_at: datetime

    model_config = {"from_attributes": True}


class ReferenceDocsListResponse(BaseModel):
    items: list[ReferenceDocResponse]
    total: int


class ReferenceDocDeleteResponse(BaseModel):
    status: str
    message: str


class ReferenceDocProcessResponse(BaseModel):
    status: str
    doc_id: str | None = None
    chunks_count: int | None = None
    error: str | None = None
