"""
Servicio para procesar documentos de referencia (category=reference).

Los documentos de referencia:
  - Se parsean, chunkean y embeben igual que los curados
  - NO generan sugerencias ni pasan por redundancy_detection
  - Se marcan como status=approved automáticamente tras el procesamiento
  - Almacenan metadata adicional category=reference en ChromaDB
"""

import logging
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.models import Document, DocumentCategory, DocumentChunk, DocumentStatus
from app.rag.embeddings import chunk_and_embed as embed_chunks
from app.utils.parser import parse_document

logger = logging.getLogger(__name__)


async def process_reference_document(
    doc_id: uuid.UUID,
    db: AsyncSession | None = None,
) -> dict:
    """Procesa un único documento de referencia: parsea, chunkea y embebe.

    A diferencia del pipeline de curación, este flujo:
      - NO genera sugerencias
      - NO pasa por redundancy_detection
      - Marca el documento como 'approved' directamente

    Args:
        doc_id: UUID del documento a procesar.
        db: Sesión opcional de base de datos (se crea una si no se provee).

    Returns:
        Dict con resultado del procesamiento.
    """
    should_close_db = db is None
    if db is None:
        db = AsyncSessionLocal()

    try:
        result = await db.execute(select(Document).where(Document.id == doc_id))
        doc = result.scalar_one_or_none()

        if not doc:
            return {"status": "error", "error": f"Documento {doc_id} no encontrado"}

        if doc.category != DocumentCategory.reference:
            return {
                "status": "error",
                "error": f"Documento {doc_id} no es de tipo reference",
            }

        file_path = Path(doc.file_path)
        if not file_path.exists():
            return {"status": "error", "error": f"Archivo no encontrado: {file_path}"}

        logger.info(
            "📄 Procesando referencia: %s (%s)", doc.original_filename, doc.file_type
        )

        # Marcar como processing
        doc.status = DocumentStatus.processing
        await db.flush()

        # 1. Parsear
        text = parse_document(str(file_path))
        logger.info("   Texto extraído: %d caracteres", len(text))

        # 2. Chunk + embed con category=reference
        chunk_results = embed_chunks(
            text=text,
            doc_id=str(doc.id),
            category="reference",
        )
        logger.info("   Chunks generados: %d", len(chunk_results))

        # 3. Persistir chunks en Postgres
        for c in chunk_results:
            chunk_record = DocumentChunk(
                document_id=doc.id,
                chunk_index=c["chunk_index"],
                content=c["text"],
                token_count=c["token_count"],
                chroma_id=c["chroma_id"],
                page_number=c.get("page_number"),
                hash=c.get("hash"),
            )
            db.add(chunk_record)

        # 4. Marcar como approved (procesado y disponible)
        doc.status = DocumentStatus.approved
        await db.flush()

        if should_close_db:
            await db.commit()

        logger.info(
            "  ✅ Referencia %s procesada exitosamente (%d chunks)",
            doc_id,
            len(chunk_results),
        )

        return {
            "status": "success",
            "doc_id": str(doc.id),
            "chunks_count": len(chunk_results),
        }

    except Exception as e:
        logger.error("  ❌ Error procesando referencia %s: %s", doc_id, e)
        if should_close_db:
            await db.rollback()
        return {"status": "error", "error": str(e)}
    finally:
        if should_close_db and db:
            await db.close()


async def process_all_pending_references() -> list[dict]:
    """Procesa todos los documentos de referencia pendientes.

    Busca documentos con category=reference y status=needs_review o processing,
    y ejecuta el pipeline de procesamiento para cada uno.

    Returns:
        Lista de resultados por documento.
    """
    results: list[dict] = []

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Document).where(
                Document.category == DocumentCategory.reference,
                Document.status.in_(
                    [DocumentStatus.needs_review, DocumentStatus.processing]
                ),
            )
        )
        docs = list(result.scalars().all())

        if not docs:
            logger.info("  ℹ️  No hay documentos de referencia pendientes")
            return []

        logger.info("📚 Procesando %d documento(s) de referencia", len(docs))

        for doc in docs:
            res = await process_reference_document(doc.id, db=db)
            results.append(res)

        await db.commit()

    return results


async def delete_reference_chunks(
    doc_id: uuid.UUID,
    chroma_ids: list[str],
) -> None:
    """Elimina chunks de ChromaDB para un documento de referencia."""
    from app.rag.embeddings import get_chroma_collection

    if not chroma_ids:
        return

    try:
        collection = get_chroma_collection()
        collection.delete(ids=chroma_ids)
        logger.info(
            "  🗑️  Eliminados %d chunks de ChromaDB para referencia %s",
            len(chroma_ids),
            doc_id,
        )
    except Exception as e:
        logger.error("  ❌ Error eliminando chunks de ChromaDB para %s: %s", doc_id, e)
