"""Distinguir la confianza medida de la ausencia de ranking semántico

Cuando el chat responde con el respaldo de Postgres (sin búsqueda vectorial)
no hay similitud que medir. Antes se guardaba un 0.5 inventado que la UI
mostraba como "Confianza: 50%", indistinguible de una medición real.

Las filas existentes se marcan según ese síntoma: confianza exactamente 0.5
con contexto es, por construcción, una respuesta del respaldo.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_history",
        sa.Column(
            "confidence_available",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    # El 0.5 exacto sólo lo producía el respaldo de Postgres (similarity
    # fija 0.5 en cada chunk); una media de similitudes reales no cae ahí.
    op.execute(
        """
        UPDATE chat_history
           SET confidence_available = false,
               confidence = 0.0
         WHERE has_context = true
           AND confidence = 0.5
        """
    )


def downgrade() -> None:
    op.drop_column("chat_history", "confidence_available")
