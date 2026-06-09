"""
#12 — Nodos del grafo LangGraph para el agente de curación.

Cada función es un nodo del grafo. Reciben el estado actual (AgentState)
y retornan un dict con las actualizaciones a aplicar sobre el estado.

Nodos:
  load_documents_node    — Carga documentos pendientes (status=needs_review)
  chunk_and_embed_node   — Parsea, chunkea y embebe cada documento
  agent_node             — LLM con herramientas (ReAct loop via subgraph)
  generate_suggestions_node
                         — Convierte output del agente en Suggestions en DB
  wait_human_approval_node
                         — Marca docs como listos para revisión humana
"""

import json
import logging
import uuid
from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.models import (
    Document,
    DocumentChunk,
    DocumentHistory,
    DocumentStatus,
    Suggestion,
    SuggestionStatus,
    SuggestionType,
)
from app.rag.embeddings import chunk_and_embed as embed_chunks
from app.tools.guardrails import ToolOutputValidationError
from app.utils.parser import parse_document

logger = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _format_doc_context(state: dict) -> str:
    """Construye el contexto que recibe el agente con los docs y chunks disponibles."""
    n_docs = len(state.get("document_ids", []))
    n_chunks = len(state.get("chunks", []))
    doc_list = "\n".join(
        f"  - Documento {i + 1}: id={doc_id}"
        for i, doc_id in enumerate(state.get("document_ids", []))
    )
    return (
        f"Documentos cargados: {n_docs}\n"
        f"{doc_list}\n"
        f"Chunks generados: {n_chunks}\n"
        f"Contenido disponible para análisis."
    )


def _validate_suggestion_fields(args: dict) -> None:
    """Valida que los campos requeridos estén presentes en una sugerencia.

    Args:
        args: Diccionario con los argumentos de la sugerencia.

    Raises:
        ToolOutputValidationError: Si falta algún campo requerido.
    """
    required_fields = {
        "source_doc_id": "ID del documento fuente",
        "confidence_score": "Puntaje de confianza del agente",
        "source_chunk_ids": "Lista de IDs de chunks fuente",
    }

    missing = []
    for field, desc in required_fields.items():
        value = args.get(field)
        if field == "confidence_score":
            if value is None or not isinstance(value, (int, float)):
                missing.append(f"{field} ({desc})")
            elif value < 0.0 or value > 1.0:
                raise ToolOutputValidationError(
                    f"Campo '{field}' con valor {value} fuera de rango [0.0, 1.0]"
                )
        elif field == "source_chunk_ids":
            if value is None or not isinstance(value, list) or not value:
                missing.append(f"{field} ({desc})")
        elif field == "source_doc_id":
            if not value or not isinstance(value, str):
                missing.append(f"{field} ({desc})")
        else:
            if value is None:
                missing.append(f"{field} ({desc})")

    if missing:
        raise ToolOutputValidationError(
            f"Sugerencia rechazada: campos requeridos faltantes o inválidos: {', '.join(missing)}"
        )


# ── Nodo 1: load_documents_node ──────────────────────────────────────────────


async def load_documents_node(state: dict) -> dict:
    """Carga documentos con status needs_review desde Postgres.

    Marca los documentos como 'processing' para evitar
    que otro worker los procese concurrentemente.
    """
    logger.info("=" * 50)
    logger.info("📂 load_documents_node — buscando documentos pendientes")
    logger.info("=" * 50)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Document).where(Document.status == DocumentStatus.needs_review)
        )
        docs = list(result.scalars().all())

        if not docs:
            logger.info("  ℹ️  No hay documentos pendientes de procesar")
            return {"document_ids": [], "error": None}

        doc_ids: list[str] = []
        for doc in docs:
            doc_ids.append(str(doc.id))
            doc.status = DocumentStatus.processing
            logger.info("  → Marcando %s como 'processing'", doc.id)

        await db.commit()
        logger.info("  ✅ Cargados %d documentos: %s", len(doc_ids), doc_ids)
        return {"document_ids": doc_ids, "error": None}


# ── Nodo 2: chunk_and_embed_node ─────────────────────────────────────────────


async def chunk_and_embed_node(state: dict) -> dict:
    """Parsea, chunkea y embebe cada documento pendiente.

    Para cada documento:
      1. Lee el archivo del disco
      2. Extrae texto plano vía parser.py
      3. Chunk + embedding vía rag/embeddings.py
      4. Persiste los chunks en document_chunks (Postgres)
      5. Almacena el texto extraído en state['documents_text']
    """
    logger.info("=" * 50)
    logger.info("🔧 chunk_and_embed_node — procesando documentos")
    logger.info("=" * 50)

    doc_ids = state.get("document_ids", [])
    if not doc_ids:
        logger.info("  ℹ️  No hay documentos que procesar")
        return {"chunks": [], "documents_text": {}}

    all_chunks: list[dict] = []
    documents_text: dict[str, str] = {}
    errors: list[str] = []

    async with AsyncSessionLocal() as db:
        for doc_id_str in doc_ids:
            try:
                doc_uuid = uuid.UUID(doc_id_str)
                result = await db.execute(
                    select(Document).where(Document.id == doc_uuid)
                )
                doc = result.scalar_one_or_none()

                if not doc:
                    errors.append(f"Documento {doc_id_str} no encontrado en DB")
                    continue

                file_path = Path(doc.file_path)
                if not file_path.exists():
                    errors.append(f"Archivo no encontrado: {file_path}")
                    continue

                logger.info(
                    "  📄 Procesando: %s (%s)", doc.original_filename, doc.file_type
                )

                # 1. Parsear
                text = parse_document(str(file_path))
                documents_text[doc_id_str] = text
                logger.info("     Texto extraído: %d caracteres", len(text))

                # 2. Chunk + embed
                chunk_results = embed_chunks(
                    text=text,
                    doc_id=doc_id_str,
                )
                all_chunks.extend(chunk_results)
                logger.info("     Chunks generados: %d", len(chunk_results))

                # 3. Persistir chunks en Postgres
                for c in chunk_results:
                    chunk_record = DocumentChunk(
                        document_id=doc_uuid,
                        chunk_index=c["chunk_index"],
                        content=c["text"],
                        token_count=c["token_count"],
                        chroma_id=c["chroma_id"],
                        page_number=c.get("page_number"),
                        hash=c.get("hash"),
                    )
                    db.add(chunk_record)

                # 4. Actualizar timestamp
                await db.flush()
                logger.info("  ✅ Documento %s procesado exitosamente", doc_id_str)

            except Exception as e:
                logger.error("  ❌ Error procesando documento %s: %s", doc_id_str, e)
                errors.append(f"{doc_id_str}: {e}")

        await db.commit()

    # Si hubo errores, los registramos pero continuamos con lo que se pudo procesar
    error_msg = "; ".join(errors) if errors else None
    if error_msg:
        logger.warning("  ⚠️  Errores durante chunk_and_embed: %s", error_msg)

    return {
        "chunks": all_chunks,
        "documents_text": documents_text,
        "error": error_msg if error_msg else state.get("error"),
    }


# ── Nodo 3: redundancy_detection_node ────────────────────────────────────────


async def redundancy_detection_node(state: dict) -> dict:
    """Detecta redundancia semántica entre los chunks generados.

    Ejecuta detect_redundancy_bulk sobre todos los chunks del estado
    y agrega los resultados al estado como redundancy_findings.
    Cada par redundante con similarity > threshold se registra.
    """
    logger.info("=" * 50)
    logger.info("🔍 redundancy_detection_node — detectando redundancias")
    logger.info("=" * 50)

    chunks = state.get("chunks", [])
    if not chunks:
        logger.info("  ℹ️  No hay chunks para analizar")
        return {"redundancy_findings": []}

    chunk_ids = [c.get("chroma_id", "") for c in chunks if c.get("chroma_id")]
    if not chunk_ids:
        logger.info("  ℹ️  No hay chroma_ids en los chunks")
        return {"redundancy_findings": []}

    from app.rag.redundancy import detect_redundancy_bulk

    try:
        reports = await detect_redundancy_bulk(
            chunk_ids=chunk_ids,
            max_pairs_per_chunk=10,
            include_same_doc=True,
        )

        # Consolidar todos los pares redundantes
        all_findings: list[dict] = []
        for report in reports:
            for pair in report.redundant_pairs:
                all_findings.append(
                    {
                        "chunk_id_a": pair.chunk_id_a,
                        "chunk_id_b": pair.chunk_id_b,
                        "similarity": pair.similarity,
                        "confidence_score": pair.confidence_score,
                        "doc_id_a": pair.doc_id_a,
                        "doc_id_b": pair.doc_id_b,
                    }
                )

        logger.info(
            "  ✅ Redundancia: %d pares únicos encontrados",
            len(all_findings),
        )
        return {"redundancy_findings": all_findings}

    except Exception as e:
        logger.error("  ❌ Error detectando redundancias: %s", e)
        return {"redundancy_findings": []}


# ── Nodo 4: agent_node — (se usa directamente create_react_agent como subgraph) ──

# El nodo agent_node y tool_executor_node están encapsulados dentro del subgraph
# que crea create_react_agent() en graph.py. Este archivo solo exporta los nodos
# personalizados del grafo principal.


# ── Nodo 5: generate_suggestions_node ────────────────────────────────────────


async def generate_suggestions_node(state: dict) -> dict:
    """Procesa las respuestas del agente y crea sugerencias en Postgres.

    También procesa los hallazgos de redundancia detectados automáticamente
    por redundancy_detection_node, creando sugerencias de tipo 'redundancy'
    para cada par redundante encontrado.

    Flujo:
      1. Procesa tool calls de suggest_update del agente ReAct
      2. Procesa redundancy_findings del nodo de detección automática
      3. Persiste todo en Postgres con estado 'pending'
    """
    logger.info("=" * 50)
    logger.info("💡 generate_suggestions_node — generando sugerencias")
    logger.info("=" * 50)

    suggestions: list[dict] = []
    messages = state.get("messages", [])
    redundancy_findings = state.get("redundancy_findings", [])

    async with AsyncSessionLocal() as db:
        # ── 1. Procesar resultados del agente ReAct ────────────────────────
        for msg in messages:
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    if tc.get("name") != "suggest_update":
                        continue
                    try:
                        _validate_suggestion_fields(tc.get("args", {}))
                        logger.info(
                            "  ✅ Tool call suggest_update validado; la tool persiste la sugerencia"
                        )
                    except ToolOutputValidationError as e:
                        logger.warning(
                            "  ⚠️  Tool call suggest_update rechazado por guardrails: %s",
                            e,
                        )

            if (
                isinstance(msg, ToolMessage)
                and getattr(msg, "name", "") == "suggest_update"
            ):
                try:
                    if not isinstance(msg.content, str):
                        continue
                    payload = json.loads(msg.content)
                    if payload.get("status") != "success":
                        continue
                    suggestions.append(
                        {
                            "id": payload["suggestion_id"],
                            "document_id": payload["document_id"],
                            "type": payload["type"],
                            "description": payload.get("message", ""),
                            "confidence_score": payload["confidence_score"],
                        }
                    )
                    logger.info(
                        "  ✅ Sugerencia del agente registrada por tool: %s",
                        payload["suggestion_id"],
                    )
                except Exception as e:
                    logger.warning(
                        "  ⚠️  No se pudo leer resultado suggest_update: %s", e
                    )

        # ── 2. Procesar hallazgos de redundancia automática ────────────────
        for finding in redundancy_findings:
            try:
                chunk_id_a = finding.get("chunk_id_a", "")
                chunk_id_b = finding.get("chunk_id_b", "")
                doc_id_a = finding.get("doc_id_a", "")
                doc_id_b = finding.get("doc_id_b", "")
                similarity = finding.get("similarity", 0.0)
                confidence = finding.get("confidence_score", 0.0)

                # Usar doc_id_a como documento principal para la sugerencia
                if not doc_id_a:
                    continue

                # Validar que los campos requeridos existen
                if not chunk_id_a or not chunk_id_b:
                    logger.warning(
                        "  ⚠️  Hallazgo de redundancia sin chunk_ids, saltando"
                    )
                    continue
                if (
                    not isinstance(confidence, (int, float))
                    or confidence < 0.0
                    or confidence > 1.0
                ):
                    logger.warning(
                        "  ⚠️  confidence_score inválido (%s) en hallazgo de redundancia, "
                        "usando 0.0",
                        confidence,
                    )
                    confidence = 0.0

                doc_uuid = uuid.UUID(doc_id_a)
                description = (
                    f"Información redundante detectada entre chunks "
                    f"'{chunk_id_a}' y '{chunk_id_b}' "
                    f"(similitud: {similarity:.2f}). "
                    f"Se recomienda consolidar para evitar duplicidad."
                )
                reasoning = (
                    f"Detección automática de redundancia:\n"
                    f"- Chunk A: {chunk_id_a} (documento: {doc_id_a})\n"
                    f"- Chunk B: {chunk_id_b} (documento: {doc_id_b})\n"
                    f"- Similitud coseno: {similarity:.4f}\n"
                    f"- Threshold usado: {settings.REDUNDANCY_THRESHOLD}\n"
                )

                suggestion = Suggestion(
                    document_id=doc_uuid,
                    type=SuggestionType.redundancy,
                    description=description,
                    source_doc_id=doc_id_a,
                    source_chunk_ids=[chunk_id_a, chunk_id_b],
                    confidence_score=confidence,
                    reasoning=reasoning,
                    status=SuggestionStatus.pending,
                )
                db.add(suggestion)
                await db.flush()

                suggestion_data = {
                    "id": str(suggestion.id),
                    "document_id": doc_id_a,
                    "type": "redundancy",
                    "description": description,
                    "confidence_score": confidence,
                }
                suggestions.append(suggestion_data)
                logger.info(
                    "  ✅ Sugerencia redundancia: %s (score=%.2f, sim=%.2f)",
                    suggestion.id,
                    confidence,
                    similarity,
                )

            except Exception as e:
                logger.error("  ❌ Error creando sugerencia de redundancia: %s", e)

        await db.commit()

    if not suggestions:
        logger.info("  ℹ️  No se generaron sugerencias nuevas")

    # Extraer también el razonamiento del último mensaje del agente
    reasoning_text = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            reasoning_text = msg.content
            break

    logger.info("  📝 Razonamiento del agente: %d caracteres", len(reasoning_text))
    logger.info("  📊 Sugerencias totales generadas: %d", len(suggestions))

    return {"suggestions": suggestions}


# ── Nodo 5: wait_human_approval_node ─────────────────────────────────────────


async def wait_human_approval_node(state: dict) -> dict:
    """Punto de espera para revisión humana.

    Este nodo NO modifica ningún contenido oficial.
    Solo cambia el status de los documentos a 'needs_review'
    para que el instructor los revise en la UI.
    """
    logger.info("=" * 50)
    logger.info("⏳ wait_human_approval_node — esperando revisión humana")
    logger.info("=" * 50)

    doc_ids = state.get("document_ids", [])
    suggestions = state.get("suggestions", [])

    if not doc_ids:
        logger.info("  ℹ️  No hay documentos que actualizar")
        return {}

    async with AsyncSessionLocal() as db:
        for doc_id_str in doc_ids:
            try:
                doc_uuid = uuid.UUID(doc_id_str)
                result = await db.execute(
                    select(Document).where(Document.id == doc_uuid)
                )
                doc = result.scalar_one_or_none()

                if not doc:
                    continue

                # Volver a needs_review para que el instructor revise
                doc.status = DocumentStatus.needs_review

                # Audit trail
                history = DocumentHistory(
                    doc_id=doc_uuid,
                    action="agent_completed",
                    performed_by=None,  # Acción del sistema, no de un usuario
                    before_content={"status": "processing"},
                    after_content={
                        "status": "needs_review",
                        "suggestions_count": len(
                            [
                                s
                                for s in suggestions
                                if s.get("document_id") == doc_id_str
                            ]
                        ),
                    },
                    reason="Procesamiento por agente completado. Pendiente revisión humana.",
                )
                db.add(history)
                logger.info("  → Documento %s: processing → needs_review", doc_id_str)

            except Exception as e:
                logger.error("  ❌ Error actualizando documento %s: %s", doc_id_str, e)

        await db.commit()

    n_new_suggestions = len(suggestions)
    logger.info("  📊 Total sugerencias generadas: %d", n_new_suggestions)
    logger.info("=" * 50)
    logger.info("✅ Grafo completado — esperando revisión del instructor")
    logger.info("=" * 50)

    return {}
