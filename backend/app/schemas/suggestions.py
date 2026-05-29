import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.models import SuggestionStatus, SuggestionType


class SuggestionResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    type: SuggestionType
    description: str
    source_doc_id: str
    source_chunk_ids: list[str]
    confidence_score: float
    reasoning: str | None
    status: SuggestionStatus
    reviewed_by: uuid.UUID | None
    review_reason: str | None
    created_at: datetime
    reviewed_at: datetime | None
    document_name: str | None = None

    model_config = {"from_attributes": True}


class SuggestionsListResponse(BaseModel):
    items: list[SuggestionResponse]
    total: int


class ApproveResponse(BaseModel):
    id: uuid.UUID
    status: SuggestionStatus
    message: str


class RejectRequest(BaseModel):
    reason: str


class RejectResponse(BaseModel):
    id: uuid.UUID
    status: SuggestionStatus
    message: str
