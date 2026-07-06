"""
Servicio para obtener el contenido original de chunks como evidencia
para la UI de revisión de sugerencias (Issue #33 — Zero Hallucinations).
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import DocumentChunk

logger = logging.getLogger(__name__)


class ChunkEvidence:
    """Contenedor simple para la evidencia de un chunk."""

    def __init__(
        self,
        chunk_id: str,
        content: str,
        chunk_index: int,
        token_count: int,
        page_number: int | None = None,
        doc_id: str | None = None,
    ):
        self.chunk_id = chunk_id
        self.content = content
        self.chunk_index = chunk_index
        self.token_count = token_count
        self.page_number = page_number
        self.doc_id = doc_id


async def get_chunks_evidence(
    db: AsyncSession,
    chunk_ids: list[str],
    *,
    max_length: int = 1000,
) -> list[dict]:
    """Busca el contenido de chunks por su chroma_id y retorna evidencia truncada.

    Args:
        db: Sesión asíncrona de base de datos.
        chunk_ids: Lista de chroma_ids (ej: ``["doc_uuid_chunk_0"]``) o UUIDs.
        max_length: Máximo de caracteres a retornar por chunk (default 1000).
            Si el contenido es más largo, se trunca con '…'.

    Returns:
        Lista de dicts con:
            - chunk_id: str
            - content: str (truncado a ``max_length``)
            - chunk_index: int
            - token_count: int
            - page_number: int | None
    """
    if not chunk_ids:
        return []

    results: list[dict] = []
    seen: set[str] = set()

    for cid in chunk_ids:
        if cid in seen:
            continue
        seen.add(cid)

        try:
            # Intentar buscar por chroma_id (formato "doc_uuid_chunk_N").
            # scalars().first() en vez de scalar_one_or_none(): si un
            # reprocesamiento dejó filas duplicadas con el mismo chroma_id,
            # cualquiera sirve (contenido idéntico) — antes fallaba con
            # "Multiple rows were found".
            result = await db.execute(
                select(DocumentChunk)
                .where(DocumentChunk.chroma_id == cid)
                .limit(1)
            )
            chunk = result.scalars().first()

            # Fallback: buscar por UUID si el chroma_id es un UUID válido
            if chunk is None:
                try:
                    uid = uuid.UUID(cid)
                    result = await db.execute(
                        select(DocumentChunk).where(DocumentChunk.id == uid)
                    )
                    chunk = result.scalar_one_or_none()
                except (ValueError, Exception):
                    pass

            if chunk is None:
                logger.debug("Chunk no encontrado: %s", cid)
                results.append(
                    {
                        "chunk_id": cid,
                        "content": "[chunk no disponible]",
                        "chunk_index": -1,
                        "token_count": 0,
                        "page_number": None,
                    }
                )
                continue

            content = chunk.content
            if len(content) > max_length:
                content = content[:max_length] + "…"

            results.append(
                {
                    "chunk_id": cid,
                    "content": content,
                    "chunk_index": chunk.chunk_index,
                    "token_count": chunk.token_count,
                    "page_number": chunk.page_number,
                }
            )

        except Exception as e:
            logger.warning("Error obteniendo evidencia del chunk %s: %s", cid, e)
            results.append(
                {
                    "chunk_id": cid,
                    "content": "[error al cargar evidencia]",
                    "chunk_index": -1,
                    "token_count": 0,
                    "page_number": None,
                }
            )

    return results
