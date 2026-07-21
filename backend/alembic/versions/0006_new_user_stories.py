"""Academic profile, processing states, roles and token usage (HU-23/29/30/32)

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_DOC_STATUSES = ("queued", "analyzed", "error")


def upgrade() -> None:
    # ── HU-29: perfil académico del docente ───────────────────────────────
    op.add_column("users", sa.Column("full_name", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("profession", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("subjects", postgresql.JSON(), nullable=True))
    op.add_column("users", sa.Column("specialties", postgresql.JSON(), nullable=True))
    op.add_column(
        "users", sa.Column("courses_taught", postgresql.JSON(), nullable=True)
    )

    # ── HU-23: nuevos estados de procesamiento + mensaje de error ─────────
    # ALTER TYPE ... ADD VALUE no puede correr dentro de una transacción en
    # versiones antiguas de Postgres; COMMIT explícito por compatibilidad.
    op.execute("COMMIT")
    for value in _NEW_DOC_STATUSES:
        op.execute(
            f"ALTER TYPE documentstatus ADD VALUE IF NOT EXISTS '{value}'"
        )

    op.add_column("documents", sa.Column("error_message", sa.Text(), nullable=True))

    # ── HU-30: roles personalizados ───────────────────────────────────────
    op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(50), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("permissions", postgresql.JSON(), nullable=True),
        sa.Column(
            "is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_roles_name", "roles", ["name"], unique=True)

    # Roles base del sistema (inmutables desde la API)
    op.execute(
        """
        INSERT INTO roles (id, name, description, permissions, is_system)
        VALUES
          (gen_random_uuid(), 'admin', 'Acceso completo al sistema',
           '["*"]'::json, true),
          (gen_random_uuid(), 'instructor', 'Docente: sube y revisa documentos',
           '["docs:read","docs:write","suggestions:review"]'::json, true)
        ON CONFLICT (name) DO NOTHING
        """
    )

    # ── HU-32: consumo de tokens del LLM ──────────────────────────────────
    op.create_table(
        "token_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("operation", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("thread_id", sa.String(100), nullable=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_token_usage_operation", "token_usage", ["operation"])
    op.create_index("ix_token_usage_model", "token_usage", ["model"])
    op.create_index("ix_token_usage_created_at", "token_usage", ["created_at"])
    op.create_index("ix_token_usage_thread_id", "token_usage", ["thread_id"])


def downgrade() -> None:
    op.drop_table("token_usage")
    op.drop_index("ix_roles_name", table_name="roles")
    op.drop_table("roles")
    op.drop_column("documents", "error_message")
    for col in ("courses_taught", "specialties", "subjects", "profession", "full_name"):
        op.drop_column("users", col)
    # Los valores añadidos al enum documentstatus no se revierten:
    # PostgreSQL no soporta DROP VALUE en tipos enum.
