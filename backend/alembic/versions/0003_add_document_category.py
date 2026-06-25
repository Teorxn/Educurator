"""Add DocumentCategory enum and category column to documents

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the PostgreSQL enum type first (avoids "type does not exist" errors).
    doc_category_enum = ENUM("curated", "reference", name="documentcategory")
    doc_category_enum.create(op.get_bind(), checkfirst=True)

    # Add column with default 'curated' so existing rows are backfilled.
    op.add_column(
        "documents",
        sa.Column(
            "category",
            doc_category_enum,
            nullable=False,
            server_default="curated",
        ),
    )
    op.create_index("ix_documents_category", "documents", ["category"])


def downgrade() -> None:
    op.drop_index("ix_documents_category", "documents")
    op.drop_column("documents", "category")
    op.execute("DROP TYPE IF EXISTS documentcategory")
