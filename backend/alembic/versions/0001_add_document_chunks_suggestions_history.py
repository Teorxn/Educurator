"""Add document_chunks, suggestions, document_history, feedback_patterns

Revision ID: 0001
Revises:
Create Date: 2026-05-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users
    op.create_table(
        "users",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.String(255), unique=True, nullable=False, index=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column(
            "role",
            sa.Enum("instructor", "admin", name="userrole"),
            nullable=False,
            server_default="instructor",
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )

    # documents
    op.create_table(
        "documents",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("file_type", sa.String(10), nullable=False),
        sa.Column("file_path", sa.String(512), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "needs_review",
                "processing",
                "approved",
                "rejected",
                "archived",
                name="documentstatus",
            ),
            nullable=False,
            server_default="needs_review",
        ),
        sa.Column(
            "uploaded_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column(
            "uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_documents_status", "documents", ["status"])

    # document_chunks
    op.create_table(
        "document_chunks",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("chroma_id", sa.String(255), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("hash", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_document_chunks_document_id", "document_chunks", ["document_id"]
    )
    op.create_index("ix_document_chunks_hash", "document_chunks", ["hash"])

    # suggestions — uses document_id FK, review_reason, source_chunk_ids JSON
    op.create_table(
        "suggestions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id"),
            nullable=False,
        ),
        sa.Column(
            "type",
            sa.Enum("redundancy", "conflict", "faq", "update", name="suggestiontype"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source_doc_id", sa.String(255), nullable=False, server_default=""),
        sa.Column("source_chunk_ids", JSON, nullable=False, server_default="[]"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "rejected", name="suggestionstatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "reviewed_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_suggestions_document_id", "suggestions", ["document_id"])
    op.create_index("ix_suggestions_status", "suggestions", ["status"])

    # document_history — immutable audit trail
    op.create_table(
        "document_history",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "doc_id", UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False
        ),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column(
            "performed_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column("before_content", JSON, nullable=True),
        sa.Column("after_content", JSON, nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index("ix_document_history_doc_id", "document_history", ["doc_id"])
    op.create_index("ix_document_history_timestamp", "document_history", ["timestamp"])

    # feedback_patterns — instructor feedback for agent improvement
    op.create_table(
        "feedback_patterns",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "suggestion_id",
            UUID(as_uuid=True),
            sa.ForeignKey("suggestions.id"),
            nullable=False,
        ),
        sa.Column("feedback_type", sa.String(20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_feedback_patterns_suggestion_id", "feedback_patterns", ["suggestion_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_feedback_patterns_suggestion_id", "feedback_patterns")
    op.drop_table("feedback_patterns")
    op.drop_index("ix_document_history_timestamp", "document_history")
    op.drop_index("ix_document_history_doc_id", "document_history")
    op.drop_table("document_history")
    op.drop_index("ix_suggestions_status", "suggestions")
    op.drop_index("ix_suggestions_document_id", "suggestions")
    op.drop_table("suggestions")
    op.execute("DROP TYPE IF EXISTS suggestionstatus")
    op.execute("DROP TYPE IF EXISTS suggestiontype")
    op.drop_index("ix_document_chunks_hash", "document_chunks")
    op.drop_index("ix_document_chunks_document_id", "document_chunks")
    op.drop_table("document_chunks")
    op.drop_index("ix_documents_status", "documents")
    op.drop_table("documents")
    op.execute("DROP TYPE IF EXISTS documentstatus")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS userrole")
