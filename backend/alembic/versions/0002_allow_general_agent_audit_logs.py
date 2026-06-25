"""Allow general agent audit logs without document FK

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-08
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "document_history",
        "doc_id",
        existing_type=UUID(as_uuid=True),
        nullable=True,
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "document_history",
        "doc_id",
        existing_type=UUID(as_uuid=True),
        nullable=False,
        existing_nullable=True,
    )
