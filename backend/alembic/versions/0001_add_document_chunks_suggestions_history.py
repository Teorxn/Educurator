"""Add document_chunks, suggestions, document_history

Revision ID: 0001
Revises:
Create Date: 2026-05-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # document_chunks
    op.create_table(
        "document_chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False, index=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("chroma_id", sa.String(255), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("hash", sa.String(64), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # suggestions
    op.create_table(
        "suggestions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False, index=True),
        sa.Column("type", sa.Enum("redundancy", "conflict", "faq", name="suggestiontype"), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source_doc_id", sa.String(255), nullable=False),
        sa.Column("source_chunk_ids", JSON, nullable=False, default=list),
        sa.Column("confidence_score", sa.Float(), nullable=False, default=0.0),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("status", sa.Enum("pending", "approved", "rejected", name="suggestionstatus"), nullable=False, index=True, server_default="pending"),
        sa.Column("reviewed_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # document_history
    op.create_table(
        "document_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("doc_id", UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False, index=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("performed_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("before_content", JSON, nullable=True),
        sa.Column("after_content", JSON, nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("document_history")
    op.drop_table("suggestions")
    op.execute("DROP TYPE IF EXISTS suggestionstatus")
    op.execute("DROP TYPE IF EXISTS suggestiontype")
    op.drop_table("document_chunks")
