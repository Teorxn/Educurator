"""
HU-22 / HU-23 — Cola de curación secuencial con estados de procesamiento.

Varios uploads simultáneos no deben lanzar N pipelines RAG en paralelo
(cada uno carga el modelo de embeddings, hace OCR y llama al LLM con
rate limit). Este módulo encola los documentos y un único worker los
procesa de a uno, manteniendo el estado visible para el docente:

    queued → processing → analyzed | error

El worker vive en el mismo proceso (asyncio.Queue). Si el proyecto
crece, la sustitución natural es Redis + arq/Celery sin cambiar la API
de este módulo (ver docs/despliegue-y-escalado.md).
"""

import asyncio
import logging
import uuid
from typing import Optional

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.models import Document, DocumentStatus

logger = logging.getLogger(__name__)

_queue: Optional[asyncio.Queue] = None
_worker_task: Optional[asyncio.Task] = None


def get_queue() -> asyncio.Queue:
    """Cola de documentos pendientes de curación (lazy, ligada al event loop)."""
    global _queue
    if _queue is None:
        _queue = asyncio.Queue()
    return _queue


def queue_size() -> int:
    """Documentos esperando en la cola (0 si aún no se creó)."""
    return _queue.qsize() if _queue is not None else 0


async def _set_status(
    doc_id: str,
    new_status: DocumentStatus,
    *,
    error_message: Optional[str] = None,
) -> None:
    """Actualiza el estado del documento (best-effort, nunca lanza)."""
    try:
        async with AsyncSessionLocal() as db:
            doc = (
                await db.execute(
                    select(Document).where(Document.id == uuid.UUID(doc_id))
                )
            ).scalar_one_or_none()
            if doc is None:
                return
            doc.status = new_status
            doc.error_message = error_message
            await db.commit()
            logger.info("  📍 Documento %s → %s", doc_id, new_status.value)
    except Exception as e:
        logger.warning("No se pudo actualizar el estado de %s: %s", doc_id, e)


async def _process_one(doc_id: str) -> None:
    """Ejecuta el pipeline de un documento y refleja el resultado en su estado."""
    from app.agents.graph import run_curation

    await _set_status(doc_id, DocumentStatus.processing)
    try:
        await run_curation(document_ids=[doc_id])
        # analyzed: pipeline completo, sugerencias listas para revisión
        await _set_status(doc_id, DocumentStatus.analyzed)
    except TimeoutError as e:
        logger.error("Timeout procesando documento %s: %s", doc_id, e)
        await _set_status(
            doc_id,
            DocumentStatus.error,
            error_message=(
                "El análisis excedió el tiempo máximo. Puedes reintentarlo "
                "desde la lista de documentos."
            ),
        )
    except Exception as e:
        logger.exception("Error procesando documento %s", doc_id)
        await _set_status(
            doc_id,
            DocumentStatus.error,
            error_message=f"{e.__class__.__name__}: {str(e)[:300]}",
        )


async def _worker() -> None:
    """Consume la cola de a un documento por vez (procesamiento secuencial)."""
    queue = get_queue()
    logger.info("🧵 Worker de curación iniciado")
    while True:
        doc_id = await queue.get()
        try:
            logger.info(
                "🧵 Procesando %s (%d en cola por detrás)", doc_id, queue.qsize()
            )
            await _process_one(doc_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Fallo inesperado en el worker con %s", doc_id)
        finally:
            queue.task_done()


def start_worker() -> None:
    """Arranca el worker si no está corriendo (idempotente)."""
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_worker())


def stop_worker() -> None:
    """Detiene el worker (shutdown de la app)."""
    global _worker_task
    if _worker_task is not None and not _worker_task.done():
        _worker_task.cancel()
    _worker_task = None


async def enqueue_curation(doc_id: str) -> None:
    """Encola un documento para análisis y garantiza que el worker corre."""
    start_worker()
    await _set_status(doc_id, DocumentStatus.queued)
    await get_queue().put(doc_id)
    logger.info("📥 Documento %s encolado (cola: %d)", doc_id, queue_size())
