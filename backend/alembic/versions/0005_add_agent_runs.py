"""Add agent_runs table for persistent run history (HU-19)

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    agent_run_status = postgresql.ENUM(
        "running", "completed", "failed", name="agent_run_status"
    )
    agent_run_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("thread_id", sa.String(100), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "running",
                "completed",
                "failed",
                name="agent_run_status",
                create_type=False,
            ),
            nullable=False,
            server_default="running",
        ),
        sa.Column(
            "triggered_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("documents_processed", sa.Integer(), server_default="0"),
        sa.Column("suggestions_generated", sa.Integer(), server_default="0"),
        sa.Column("summary", postgresql.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("trace_url", sa.Text(), nullable=True),
    )
    op.create_index("ix_agent_runs_thread_id", "agent_runs", ["thread_id"], unique=True)
    op.create_index("ix_agent_runs_started_at", "agent_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_runs_started_at", table_name="agent_runs")
    op.drop_index("ix_agent_runs_thread_id", table_name="agent_runs")
    op.drop_table("agent_runs")
    postgresql.ENUM(name="agent_run_status").drop(op.get_bind(), checkfirst=True)
