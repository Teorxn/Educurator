import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.models import SuggestionStatus, SuggestionType


class SuggestionResponse(BaseModel):
    id: uuid.UUID
    doc_id: uuid.UUID
    type: SuggestionType
    status: SuggestionStatus
    description: str
    reasoning: str | None
    confidence_score: float | None
    source_chunk_ids: str | None
    source_doc_id: uuid.UUID | None
    rejection_reason: str | None
    created_at: datetime
    reviewed_at: datetime | None

    model_config = {"from_attributes": True}


class SuggestionsListResponse(BaseModel):
    items: list[SuggestionResponse]
    total: int


class ApproveRequest(BaseModel):
    pass  # no body required for approve


class RejectRequest(BaseModel):
    reason: str = Field(..., min_length=1, description="Motivo del rechazo")


class FeedbackRequest(BaseModel):
    comment: str | None = None


class DocumentHistoryEntry(BaseModel):
    id: uuid.UUID
    doc_id: uuid.UUID
    action: str
    performed_by: uuid.UUID | None
    timestamp: datetime
    before_state: str | None
    after_state: str | None
    reason: str | None

    model_config = {"from_attributes": True}


class AnalyticsResponse(BaseModel):
    total_documents: int
    by_status: dict[str, int]
    total_suggestions: int
    suggestions_by_status: dict[str, int]
    suggestions_by_type: dict[str, int]
    approval_rate: float   # 0.0 – 1.0
