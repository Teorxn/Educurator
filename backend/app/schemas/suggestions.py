import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.models import SuggestionStatus, SuggestionType


class ChunkEvidenceItem(BaseModel):
    """Evidencia de un chunk individual mostrada al revisor."""

    chunk_id: str
    content: str
    chunk_index: int
    token_count: int
    page_number: int | None = None


class SuggestionResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    type: SuggestionType
    status: SuggestionStatus
    description: str
    reasoning: str | None
    confidence_score: float
    source_chunk_ids: list
    source_doc_id: str
    source_web_url: str | None = None
    source_type: str | None = None
    review_reason: str | None
    reviewed_by: uuid.UUID | None
    # HU-26 — identidad legible de quien revisó la sugerencia
    reviewed_by_email: str | None = None
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None
    created_at: datetime
    document_name: str | None = None
    source_chunks: list[ChunkEvidenceItem] = []

    model_config = {"from_attributes": True}


class SuggestionsListResponse(BaseModel):
    items: list[SuggestionResponse]
    total: int


class ApproveResponse(BaseModel):
    id: uuid.UUID
    status: SuggestionStatus
    message: str


class RejectRequest(BaseModel):
    reason: str = Field(..., min_length=1, description="Motivo del rechazo")


class RejectResponse(BaseModel):
    id: uuid.UUID
    status: SuggestionStatus
    message: str


class FeedbackRequest(BaseModel):
    comment: str | None = None


class DocumentHistoryEntry(BaseModel):
    id: uuid.UUID
    doc_id: uuid.UUID
    action: str
    performed_by: uuid.UUID | None
    timestamp: datetime
    before_content: dict | None
    after_content: dict | None
    reason: str | None

    model_config = {"from_attributes": True}


class AnalyticsResponse(BaseModel):
    total_documents: int
    by_status: dict[str, int]
    total_suggestions: int
    suggestions_by_status: dict[str, int]
    suggestions_by_type: dict[str, int]
    approval_rate: float
