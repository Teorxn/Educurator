import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


# ── Enums ────────────────────────────────────────────────────────────────────


class UserRole(str, enum.Enum):
    instructor = "instructor"
    admin = "admin"


class DocumentStatus(str, enum.Enum):
    needs_review = "needs_review"
    processing = "processing"
    approved = "approved"
    rejected = "rejected"
    archived = "archived"


class SuggestionType(str, enum.Enum):
    redundancy = "redundancy"
    conflict = "conflict"
    faq = "faq"
    update = "update"


class SuggestionStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


# ── Models ───────────────────────────────────────────────────────────────────


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), default=UserRole.instructor, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    documents: Mapped[list["Document"]] = relationship("Document", back_populates="uploader")
    reviewed_suggestions: Mapped[list["Suggestion"]] = relationship("Suggestion", back_populates="reviewer")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        SAEnum(DocumentStatus), default=DocumentStatus.needs_review, nullable=False, index=True
    )
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    uploader: Mapped["User | None"] = relationship("User", back_populates="documents")
    suggestions: Mapped[list["Suggestion"]] = relationship("Suggestion", back_populates="document")
    history: Mapped[list["DocumentHistory"]] = relationship(
        "DocumentHistory", back_populates="document", order_by="DocumentHistory.timestamp.desc()"
    )


class Suggestion(Base):
    """HU-09 / HU-11 / HU-12 / HU-14 — Sugerencias generadas por el agente."""

    __tablename__ = "suggestions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True)
    type: Mapped[SuggestionType] = mapped_column(SAEnum(SuggestionType), nullable=False, index=True)
    status: Mapped[SuggestionStatus] = mapped_column(
        SAEnum(SuggestionStatus), default=SuggestionStatus.pending, nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_chunk_ids: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON array as string
    source_doc_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document: Mapped["Document"] = relationship("Document", back_populates="suggestions")
    reviewer: Mapped["User | None"] = relationship("User", back_populates="reviewed_suggestions")
    feedback: Mapped[list["FeedbackPattern"]] = relationship("FeedbackPattern", back_populates="suggestion")


class DocumentHistory(Base):
    """HU-17 — Historial de cambios e historial de versiones (immutable)."""

    __tablename__ = "document_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)   # uploaded | approved | rejected | archived
    performed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    before_state: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON snapshot
    after_state: Mapped[str | None] = mapped_column(Text, nullable=True)    # JSON snapshot
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    document: Mapped["Document"] = relationship("Document", back_populates="history")


class FeedbackPattern(Base):
    """HU-15 / HU-16 — Retroalimentación del instructor para mejorar futuras sugerencias."""

    __tablename__ = "feedback_patterns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    suggestion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("suggestions.id"), nullable=False)
    feedback_type: Mapped[str] = mapped_column(String(20), nullable=False)   # "approve" | "reject"
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON: doc type, suggestion type, etc.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    suggestion: Mapped["Suggestion"] = relationship("Suggestion", back_populates="feedback")
