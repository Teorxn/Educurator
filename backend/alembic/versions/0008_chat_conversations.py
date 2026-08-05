"""Group chat questions into conversation threads (HU-31)

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_chat_conversations_user_id", "chat_conversations", ["user_id"]
    )
    op.create_index(
        "ix_chat_conversations_updated_at", "chat_conversations", ["updated_at"]
    )

    # Nullable: el historial existente no pertenece a ningún hilo. Se conserva
    # tal cual para no perder preguntas ya registradas.
    op.add_column(
        "chat_history",
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_chat_history_conversation",
        "chat_history",
        "chat_conversations",
        ["conversation_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_chat_history_conversation_id", "chat_history", ["conversation_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_chat_history_conversation_id", table_name="chat_history")
    op.drop_constraint(
        "fk_chat_history_conversation", "chat_history", type_="foreignkey"
    )
    op.drop_column("chat_history", "conversation_id")
    op.drop_index("ix_chat_conversations_updated_at", table_name="chat_conversations")
    op.drop_index("ix_chat_conversations_user_id", table_name="chat_conversations")
    op.drop_table("chat_conversations")
