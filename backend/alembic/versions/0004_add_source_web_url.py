"""Add source_web_url column to suggestions table

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "suggestions",
        sa.Column(
            "source_web_url",
            sa.Text(),
            nullable=True,
            comment="URL opcional de fuente web que respalda la sugerencia",
        ),
    )


def downgrade() -> None:
    op.drop_column("suggestions", "source_web_url")
