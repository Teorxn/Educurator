"""
#13 — 6 Tools del agente: search, compare, detect, suggest, FAQ, log

Implementación completa con acceso real a ChromaDB y Postgres.
Cada tool es una función async decorada con @tool de LangChain.

Tools:
  1. search_documents  — Búsqueda semántica en ChromaDB
  2. compare_content   — Comparación entre dos chunks
  3. detect_conflict   — Detección de contradicciones entre documentos
  4. suggest_update    — Creación de sugerencias (solo pending)
  5. generate_faq_entry — Generación estructurada de FAQ
  6. log_action        — Persistencia de acciones en audit trail
"""

import asyncio
import json
import logging
import uuid
from typing import List, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings
from app.rag.redundancy import _cosine_similarity
from app.tools.guardrails import ToolOutputValidationError, validate_tool_output

logger = logging.getLogger(__name__)


# ── Input schemas (Pydantic con validación estricta) ─────────────────────────


class StrictToolInput(BaseModel):
    """Base para inputs de tools: no acepta campos extra ni coerciones implícitas."""

    model_config = ConfigDict(extra="forbid", strict=True)


class SearchInput(StrictToolInput):
    """Busca chunks por similitud semántica en ChromaDB."""

    query: str = Field(
        min_length=1,
        max_length=500,
        description="Texto de búsqueda (búsqueda semántica, no literal)",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Número de resultados a retornar (1-20)",
    )


class CompareInput(StrictToolInput):
    """Compara dos chunks y retorna diferencias textuales y semánticas."""

    chunk_id_a: str = Field(
        min_length=1,
        description="ID del primer chunk en ChromaDB",
    )
    chunk_id_b: str = Field(
        min_length=1,
        description="ID del segundo chunk en ChromaDB",
    )


class DetectConflictInput(StrictToolInput):
    """Detecta contradicciones semánticas entre dos documentos."""

    doc_id_a: str = Field(
        min_length=1,
        description="ID del primer documento a comparar",
    )
    doc_id_b: str = Field(
        min_length=1,
        description="ID del segundo documento a comparar",
    )


class SuggestUpdateInput(StrictToolInput):
    """Crea una sugerencia en estado pending (NUNCA modifica directamente)."""

    document_id: str = Field(
        min_length=1,
        description="ID UUID del documento relacionado",
    )
    suggestion_type: str = Field(
        default="update",
        pattern=r"^(redundancy|conflict|faq|update)$",
        description="Tipo: redundancy | conflict | faq | update",
    )
    description: str = Field(
        min_length=10,
        max_length=2000,
        description="Descripción clara y detallada de la sugerencia",
    )
    source_doc_id: str = Field(
        min_length=1,
        description="ID del documento fuente que respalda la sugerencia",
    )
    source_chunk_ids: List[str] = Field(
        min_length=1,
        description="Lista no vacía de IDs de chunks en ChromaDB que respaldan la sugerencia",
    )
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Nivel de confianza del agente (0.0 = mínimo, 1.0 = máximo)",
    )
    reasoning: str = Field(
        default="",
        max_length=5000,
        description="Razonamiento detallado del agente que justifica la sugerencia",
    )


class FaqInput(StrictToolInput):
    """Genera un par pregunta/respuesta a partir del contenido de un chunk."""

    chunk_id: str = Field(
        min_length=1,
        description="ID del chunk fuente en ChromaDB",
    )
    chunk_content: str = Field(
        min_length=10,
        max_length=5000,
        description="Contenido textual del chunk para generar la FAQ",
    )
    topic: str = Field(
        default="general",
        max_length=100,
        description="Temática o categoría de la FAQ",
    )


class DetectRedundancyInput(StrictToolInput):
    """Detecta información redundante entre chunks usando similitud coseno."""

    chunk_id: str = Field(
        min_length=1,
        description="ID del chunk a evaluar en ChromaDB",
    )
    threshold: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Umbral de similitud coseno (0.0-1.0). "
            "Si no se especifica, usa REDUNDANCY_THRESHOLD de la configuración."
        ),
    )
    max_pairs: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Máximo número de pares redundantes a retornar",
    )
    include_same_doc: bool = Field(
        default=True,
        description="Si incluir redundancia intra-documento (chunks del mismo documento)",
    )


class LogInput(StrictToolInput):
    """Registra una acción del agente en el audit trail."""

    action: str = Field(
        min_length=1,
        max_length=100,
        description="Nombre de la acción realizada (ej: search, compare, suggest)",
    )
    detail: str = Field(
        default="",
        max_length=1000,
        description="Detalle o contexto adicional de la acción",
    )
    agent_step: str = Field(
        default="",
        max_length=50,
        description="Paso del agente en el que ocurre la acción",
    )
    document_id: Optional[str] = Field(
        default=None,
        description="ID UUID del documento relacionado, si la acción aplica a uno",
    )


def _compute_embedding(text: str) -> list[float]:
    """Genera embedding para un texto usando sentence-transformers."""
    from app.rag.embeddings import get_embedding_model

    model = get_embedding_model()
    return model.encode(text).tolist()


def _get_chroma_collection():
    """Obtiene la colección de ChromaDB."""
    from app.rag.embeddings import get_chroma_collection

    return get_chroma_collection()


# ── Tool 1: search_documents ─────────────────────────────────────────────────


@tool(args_schema=SearchInput)
async def search_documents(query: str, top_k: int = 5) -> str:
    """Busca chunks relevantes por similitud semántica en ChromaDB.

    Genera un embedding para la consulta usando el modelo local
    y busca los top_k chunks más similares en el vector store.
    Retorna el contenido, score de similitud y metadatos de cada chunk.
    """
    logger.info("🔍 search_documents(query='%s', top_k=%d)", query[:60], top_k)
    try:
        query_emb = _compute_embedding(query)
        collection = _get_chroma_collection()

        results = await asyncio.to_thread(
            collection.query,
            query_embeddings=[query_emb],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        items = []
        if results["ids"] and len(results["ids"][0]) > 0:
            for i in range(len(results["ids"][0])):
                chunk_id = results["ids"][0][i]
                distance = results["distances"][0][i] if results["distances"] else 0.0
                similarity = round(1.0 - distance, 4)

                metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                content = results["documents"][0][i] if results["documents"] else ""

                items.append(
                    {
                        "chunk_id": chunk_id,
                        "content": content[:500],  # Truncar para la respuesta
                        "similarity": similarity,
                        "metadata": {
                            "doc_id": metadata.get("doc_id", ""),
                            "chunk_index": metadata.get("chunk_index", 0),
                            "token_count": metadata.get("token_count", 0),
                        },
                    }
                )

        result = {
            "status": "success",
            "query": query,
            "results": items,
            "total": len(items),
        }
        validate_tool_output("search_documents", result)
        return json.dumps(result, ensure_ascii=False)

    except ToolOutputValidationError:
        raise
    except Exception as e:
        logger.exception("Error en search_documents")
        error_result = {
            "status": "error",
            "error": f"Error al buscar documentos: {e}",
            "results": [],
        }
        validate_tool_output("search_documents", error_result)
        return json.dumps(error_result)


# ── Tool 2: compare_content ─────────────────────────────────────────────────


@tool(args_schema=CompareInput)
async def compare_content(chunk_id_a: str, chunk_id_b: str) -> str:
    """Compara dos chunks y retorna diferencias textuales y semánticas.

    Obtiene ambos chunks desde ChromaDB, calcula la similitud coseno
    entre sus embeddings e identifica diferencias en el contenido.
    """
    logger.info("🔍 compare_content(%s, %s)", chunk_id_a, chunk_id_b)
    try:
        collection = _get_chroma_collection()

        # Obtener ambos chunks con sus embeddings
        result_a, result_b = await asyncio.gather(
            asyncio.to_thread(
                collection.get,
                ids=[chunk_id_a],
                include=["documents", "metadatas", "embeddings"],
            ),
            asyncio.to_thread(
                collection.get,
                ids=[chunk_id_b],
                include=["documents", "metadatas", "embeddings"],
            ),
        )

        if not result_a["ids"] or not result_b["ids"]:
            missing = []
            if not result_a["ids"]:
                missing.append(chunk_id_a)
            if not result_b["ids"]:
                missing.append(chunk_id_b)
            error_result = {
                "status": "error",
                "error": f"Chunks no encontrados: {', '.join(missing)}",
            }
            validate_tool_output("compare_content", error_result)
            return json.dumps(error_result, ensure_ascii=False)

        content_a = result_a["documents"][0] if result_a["documents"] else ""
        content_b = result_b["documents"][0] if result_b["documents"] else ""

        meta_a = result_a["metadatas"][0] if result_a["metadatas"] else {}
        meta_b = result_b["metadatas"][0] if result_b["metadatas"] else {}

        # Calcular similitud coseno entre embeddings
        emb_a = result_a["embeddings"][0] if result_a.get("embeddings") else None
        emb_b = result_b["embeddings"][0] if result_b.get("embeddings") else None

        similarity = 0.0
        if emb_a and emb_b:
            similarity = _cosine_similarity(emb_a, emb_b)
        else:
            # Fallback: calcular embedding sobre la marcha
            emb_a = _compute_embedding(content_a[:1000])
            emb_b = _compute_embedding(content_b[:1000])
            similarity = _cosine_similarity(emb_a, emb_b)

        # Identificar palabras únicas de cada chunk (diferencia simple)
        words_a = set(content_a.lower().split())
        words_b = set(content_b.lower().split())
        only_in_a = list(words_a - words_b)[:20]
        only_in_b = list(words_b - words_a)[:20]

        result = {
            "status": "success",
            "chunk_a": {
                "id": chunk_id_a,
                "preview": content_a[:300],
                "doc_id": meta_a.get("doc_id", ""),
                "chunk_index": meta_a.get("chunk_index", 0),
            },
            "chunk_b": {
                "id": chunk_id_b,
                "preview": content_b[:300],
                "doc_id": meta_b.get("doc_id", ""),
                "chunk_index": meta_b.get("chunk_index", 0),
            },
            "similarity": similarity,
            "differences": {
                "only_in_a": only_in_a,
                "only_in_b": only_in_b,
                "total_tokens_a": meta_a.get("token_count", 0),
                "total_tokens_b": meta_b.get("token_count", 0),
            },
        }
        validate_tool_output("compare_content", result)
        return json.dumps(result, ensure_ascii=False)

    except ToolOutputValidationError:
        raise
    except Exception as e:
        logger.exception("Error en compare_content")
        error_result = {
            "status": "error",
            "error": f"Error al comparar chunks: {e}",
        }
        validate_tool_output("compare_content", error_result)
        return json.dumps(error_result)


# ── Tool 3: detect_conflict ─────────────────────────────────────────────────


@tool(args_schema=DetectConflictInput)
async def detect_conflict(doc_id_a: str, doc_id_b: str) -> str:
    """Detecta posibles contradicciones semánticas entre dos documentos.

    Recupera todos los chunks de ambos documentos desde ChromaDB,
    los compara por pares buscando alta similitud con contenido
    potencialmente contradictorio.
    """
    logger.info("🔍 detect_conflict(%s, %s)", doc_id_a, doc_id_b)
    try:
        collection = _get_chroma_collection()

        # Obtener todos los chunks de cada documento
        chunks_a, chunks_b = await asyncio.gather(
            asyncio.to_thread(
                collection.get,
                where={"doc_id": doc_id_a},
                include=["documents", "metadatas", "embeddings"],
            ),
            asyncio.to_thread(
                collection.get,
                where={"doc_id": doc_id_b},
                include=["documents", "metadatas", "embeddings"],
            ),
        )

        if not chunks_a["ids"]:
            error_result = {
                "status": "error",
                "error": f"No se encontraron chunks para el documento {doc_id_a}",
            }
            validate_tool_output("detect_conflict", error_result)
            return json.dumps(error_result, ensure_ascii=False)
        if not chunks_b["ids"]:
            error_result = {
                "status": "error",
                "error": f"No se encontraron chunks para el documento {doc_id_b}",
            }
            validate_tool_output("detect_conflict", error_result)
            return json.dumps(error_result, ensure_ascii=False)

        # Comparar chunks por pares limitando a 100 comparaciones
        conflicts = []
        max_comparisons = min(100, len(chunks_a["ids"]) * len(chunks_b["ids"]))
        comparisons = 0

        for i in range(len(chunks_a["ids"])):
            if comparisons >= max_comparisons:
                break
            emb_a = chunks_a["embeddings"][i] if chunks_a.get("embeddings") else None
            content_a = chunks_a["documents"][i] if chunks_a["documents"] else ""
            meta_a = chunks_a["metadatas"][i] if chunks_a["metadatas"] else {}

            for j in range(len(chunks_b["ids"])):
                if comparisons >= max_comparisons:
                    break
                emb_b = (
                    chunks_b["embeddings"][j] if chunks_b.get("embeddings") else None
                )
                content_b = chunks_b["documents"][j] if chunks_b["documents"] else ""

                similarity = 0.0
                if emb_a and emb_b:
                    similarity = _cosine_similarity(emb_a, emb_b)

                # Si alta similitud pero contenido diferente, es potencial conflicto
                if similarity > 0.75:
                    conflicts.append(
                        {
                            "chunk_a_id": chunks_a["ids"][i],
                            "chunk_b_id": chunks_b["ids"][j],
                            "similarity": similarity,
                            "content_a_preview": content_a[:200],
                            "content_b_preview": content_b[:200],
                            "index_a": meta_a.get("chunk_index", 0),
                        }
                    )
                comparisons += 1

        # Ordenar por similitud descendente
        conflicts.sort(key=lambda x: x["similarity"], reverse=True)

        result = {
            "status": "success",
            "doc_a": doc_id_a,
            "doc_b": doc_id_b,
            "total_chunks_a": len(chunks_a["ids"]),
            "total_chunks_b": len(chunks_b["ids"]),
            "comparisons": comparisons,
            "conflicts": conflicts[:10],  # Máximo 10 conflictos
            "conflict_count": len(conflicts),
        }
        validate_tool_output("detect_conflict", result)
        return json.dumps(result, ensure_ascii=False)

    except ToolOutputValidationError:
        raise
    except Exception as e:
        logger.exception("Error en detect_conflict")
        error_result = {
            "status": "error",
            "error": f"Error al detectar conflictos: {e}",
        }
        validate_tool_output("detect_conflict", error_result)
        return json.dumps(error_result)


# ── Tool 4: suggest_update ──────────────────────────────────────────────────


@tool(args_schema=SuggestUpdateInput)
async def suggest_update(
    document_id: str,
    description: str,
    source_doc_id: str,
    source_chunk_ids: List[str],
    confidence_score: float,
    suggestion_type: str = "update",
    reasoning: str = "",
) -> str:
    """Crea una sugerencia en estado 'pending' para revisión humana.

    La sugerencia se guarda en Postgres con estado 'pending'.
    NUNCA modifica contenido oficial directamente.
    El instructor debe aprobar o rechazar desde la UI.
    """
    logger.info(
        "💡 suggest_update(doc=%s, type=%s, score=%.2f)",
        document_id,
        suggestion_type,
        confidence_score,
    )
    try:
        from app.database import AsyncSessionLocal
        from app.models.models import Suggestion, SuggestionStatus, SuggestionType

        doc_uuid = uuid.UUID(document_id)
        s_type = SuggestionType(suggestion_type)

        async with AsyncSessionLocal() as db:
            suggestion = Suggestion(
                document_id=doc_uuid,
                type=s_type,
                description=description,
                source_doc_id=source_doc_id,
                source_chunk_ids=source_chunk_ids,
                confidence_score=confidence_score,
                reasoning=reasoning,
                status=SuggestionStatus.pending,
            )
            db.add(suggestion)
            await db.commit()
            await db.refresh(suggestion)

            logger.info("✅ Sugerencia creada: %s (%s)", suggestion.id, suggestion_type)
            result = {
                "status": "success",
                "suggestion_id": str(suggestion.id),
                "document_id": document_id,
                "type": suggestion_type,
                "state": "pending",
                "source_doc_id": source_doc_id,
                "source_chunk_ids": source_chunk_ids,
                "confidence_score": confidence_score,
                "message": "Sugerencia creada correctamente. Pendiente de revisión humana.",
            }
            validate_tool_output("suggest_update", result)
            return json.dumps(result, ensure_ascii=False)

    except ToolOutputValidationError:
        raise
    except ValueError as e:
        error_result = {
            "status": "error",
            "error": f"ID de documento inválido: {e}",
        }
        validate_tool_output("suggest_update", error_result)
        return json.dumps(error_result)
    except Exception as e:
        logger.exception("Error al crear sugerencia")
        error_result = {
            "status": "error",
            "error": f"Error al crear sugerencia: {e}",
        }
        validate_tool_output("suggest_update", error_result)
        return json.dumps(error_result)


# ── Tool 5: generate_faq_entry ──────────────────────────────────────────────


@tool(args_schema=FaqInput)
async def generate_faq_entry(
    chunk_id: str,
    chunk_content: str,
    topic: str = "general",
) -> str:
    """Genera un par pregunta/respuesta estructurado desde un chunk educativo.

    Si hay un LLM configurado (Gemini / OpenAI / HuggingFace), lo usa para generar
    una FAQ más natural y precisa. De lo contrario, usa una heurística basada en
    extracción de oraciones como fallback.

    Siempre se basa exclusivamente en el contenido proporcionado (sin alucinaciones).
    """
    logger.info("❓ generate_faq_entry(chunk=%s, topic='%s')", chunk_id, topic)
    try:
        import re

        # Intentar uso de LLM si está disponible
        faq = await _generate_faq_with_llm(chunk_content, topic)
        if faq is not None:
            question, answer = faq
        else:
            # Fallback: heurística basada en oraciones
            sentences = re.split(r"(?<=[.!?])\s+", chunk_content.strip())
            sentences = [s.strip() for s in sentences if len(s.strip()) > 20]

            if not sentences:
                error_result = {
                    "status": "error",
                    "error": "El chunk no contiene contenido suficiente para generar una FAQ",
                }
                validate_tool_output("generate_faq_entry", error_result)
                return json.dumps(error_result, ensure_ascii=False)

            best_sentence = max(sentences, key=len)
            other_content = [s for s in sentences if s != best_sentence]

            if topic and topic != "general":
                question = f"¿Qué información hay sobre {topic} en el curso?"
            else:
                words = best_sentence.split()
                key_phrases = []
                for i, w in enumerate(words):
                    if w[0].isupper() and len(w) > 2 and i < len(words) - 1:
                        key_phrases.append(f"{w} {words[i + 1]}")
                if key_phrases:
                    question = f"¿Qué es {' '.join(key_phrases[:3])}?"
                else:
                    question = "¿Qué información se presenta sobre este tema?"

            answer = "\n".join([best_sentence] + other_content[:3])
            if len(answer) > 1000:
                answer = answer[:1000] + "..."

        result = {
            "status": "success",
            "faq": {
                "question": question,
                "answer": answer,
                "source_chunk_id": chunk_id,
                "topic": topic,
            },
        }
        validate_tool_output("generate_faq_entry", result)
        return json.dumps(result, ensure_ascii=False)

    except ToolOutputValidationError:
        raise
    except Exception as e:
        logger.exception("Error al generar FAQ")
        error_result = {
            "status": "error",
            "error": f"Error al generar FAQ: {e}",
        }
        validate_tool_output("generate_faq_entry", error_result)
        return json.dumps(error_result)


async def _generate_faq_with_llm(
    chunk_content: str,
    topic: str,
) -> Optional[tuple[str, str]]:
    """Intenta generar FAQ usando el LLM configurado.

    Returns:
        Tupla (question, answer) si hay LLM disponible, None si se debe usar fallback.
    """
    from app.agents.graph import get_llm

    llm = get_llm()
    if llm is None:
        return None

    from langchain_core.messages import HumanMessage, SystemMessage

    system_prompt = SystemMessage(
        content=(
            "Eres un asistente que genera preguntas frecuentes (FAQ) "
            "para cursos universitarios. Basándote SOLO en el contenido "
            "proporcionado, genera una pregunta relevante y su respuesta clara.\n\n"
            "REGLAS:\n"
            "- No inventes información que no esté en el texto\n"
            "- La pregunta debe ser natural y útil para un estudiante\n"
            "- La respuesta debe ser concisa (máx. 3 oraciones)\n"
            "- Responde en español\n"
            f"- Temática: {topic}"
        )
    )
    human_prompt = HumanMessage(
        content=(
            f"Genera una pregunta frecuente y su respuesta basada en este contenido:\n\n"
            f"{chunk_content[:2000]}"
        )
    )

    try:
        response = await llm.ainvoke([system_prompt, human_prompt])
        if isinstance(response.content, str):
            text = response.content.strip()
        else:
            # Handle list[str | dict] (multimodal content)
            parts = []
            for item in response.content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(item.get("text", ""))
            text = " ".join(parts).strip()

        # Intentar extraer pregunta y respuesta del formato "Q: ... A: ..." o similar
        import re

        q_match = re.search(
            r"(?:Pregunta|Q|Question)[:\s]*([^\n]+)", text, re.IGNORECASE
        )
        a_match = re.search(
            r"(?:Respuesta|R|Answer|A)[:\s]*([^\n]+)",
            text,
            re.IGNORECASE,
        )

        if q_match and a_match:
            return q_match.group(1).strip(), a_match.group(1).strip()

        # Fallback: usar la primera línea como pregunta, el resto como respuesta
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if len(lines) >= 2:
            return lines[0], " ".join(lines[1:])
        return text, text

    except Exception as e:
        logger.warning("LLM falló generando FAQ, usando fallback: %s", e)
        return None


# ── Tool 6: log_action ──────────────────────────────────────────────────


@tool(args_schema=LogInput)
async def log_action(
    action: str,
    detail: str = "",
    agent_step: str = "",
    document_id: Optional[str] = None,
) -> str:
    """Registra una acción del agente en el sistema de auditoría.

    Persiste la acción con timestamp y contexto en Postgres
    para trazabilidad completa de las decisiones del agente.
    """
    logger.info(
        "📝 log_action(action='%s', detail='%s', step='%s')",
        action,
        detail,
        agent_step,
    )
    try:
        from datetime import datetime, timezone

        from app.database import AsyncSessionLocal
        from app.models.models import DocumentHistory

        timestamp = datetime.now(timezone.utc)

        # Validar document_id solo si se provee — es opcional para acciones
        # globales del agente (ej: "agent_started", "search_completed").
        # DocumentHistory.doc_id acepta NULL.
        doc_uuid = None
        if document_id:
            try:
                doc_uuid = uuid.UUID(document_id)
            except ValueError:
                logger.warning(
                    "document_id '%s' no es un UUID válido, se omite",
                    document_id,
                )

        context = {
            "action": action,
            "detail": detail,
            "agent_step": agent_step,
            "source": "agent_tool",
        }

        async with AsyncSessionLocal() as db:
            history = DocumentHistory(
                doc_id=doc_uuid,
                action=f"agent_{action}",
                performed_by=None,
                before_content=None,
                after_content=context,
                reason=f"Acción del agente: {action}",
            )
            db.add(history)
            await db.commit()
            await db.refresh(history)

        result = {
            "status": "logged",
            "audit_log_id": str(history.id),
            "document_id": document_id,
            "action": action,
            "detail": detail,
            "agent_step": agent_step,
            "timestamp": history.timestamp.isoformat()
            if history.timestamp
            else timestamp.isoformat(),
            "context": context,
            "message": f"Acción '{action}' registrada correctamente",
        }
        validate_tool_output("log_action", result)
        return json.dumps(result, ensure_ascii=False)

    except ToolOutputValidationError:
        raise
    except Exception as e:
        logger.exception("Error en log_action")
        error_result = {
            "status": "error",
            "action": action,
            "detail": detail,
            "agent_step": agent_step,
            "error": f"Error registrando acción en Postgres: {e}",
        }
        validate_tool_output("log_action", error_result)
        return json.dumps(error_result, ensure_ascii=False)


# ── Tool 7: detect_redundancy ────────────────────────────────────────────────


@tool(args_schema=DetectRedundancyInput)
async def detect_redundancy(
    chunk_id: str,
    threshold: Optional[float] = None,
    max_pairs: int = 10,
    include_same_doc: bool = True,
) -> str:
    """Detecta información redundante entre chunks usando similitud coseno.

    Compara el embedding de un chunk contra todos los demás en ChromaDB
    y retorna aquellos pares cuya similitud coseno supere el threshold.
    Incluye confidence_score compuesto (similitud + contexto + consistencia).

    Si no se especifica threshold, usa REDUNDANCY_THRESHOLD de la config.
    """
    from app.rag.redundancy import detect_redundancy_report as core_detect
    from app.rag.redundancy import redundancy_report_to_json

    effective = threshold if threshold is not None else settings.REDUNDANCY_THRESHOLD
    logger.info(
        "🔍 detect_redundancy(chunk=%s, threshold=%.2f, max_pairs=%d, same_doc=%s)",
        chunk_id,
        effective,
        max_pairs,
        include_same_doc,
    )
    try:
        report = await core_detect(
            chunk_id=chunk_id,
            threshold=threshold,
            max_pairs=max_pairs,
            include_same_doc=include_same_doc,
        )
        result_json = redundancy_report_to_json(report)
        result = json.loads(result_json)
        validate_tool_output("detect_redundancy", result)
        return result_json

    except ToolOutputValidationError:
        raise
    except Exception as e:
        logger.exception("Error en detect_redundancy")
        error_result = {
            "status": "error",
            "error": f"Error al detectar redundancia: {e}",
            "redundant_pairs": [],
        }
        validate_tool_output("detect_redundancy", error_result)
        return json.dumps(error_result)


# ── Registro de tools ────────────────────────────────────────────────────────


def get_all_tools() -> list:
    """Retorna la lista completa de herramientas del agente."""
    return [
        search_documents,
        compare_content,
        detect_conflict,
        suggest_update,
        generate_faq_entry,
        log_action,
        detect_redundancy,
    ]


TOOL_MAP = {tool.name: tool for tool in get_all_tools()}
