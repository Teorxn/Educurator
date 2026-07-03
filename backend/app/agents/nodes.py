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

import asyncio
import json
import logging
import uuid
from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentState
from app.config import settings
from app.database import AsyncSessionLocal
from app.models.models import (
    Document,
    DocumentCategory,
    DocumentChunk,
    DocumentHistory,
    DocumentStatus,
    Suggestion,
    SuggestionStatus,
    SuggestionType,
)
from app.rag.embeddings import chunk_and_embed as embed_chunks
from app.tools.guardrails import (
    SuggestionDataValidationError,
    ToolOutputValidationError,
    validate_inconsistency_finding,
    validate_redundancy_finding,
    validate_suggestion_data,
)
from app.utils.parser import parse_document

logger = logging.getLogger(__name__)

# ── Configuración de reintentos ────────────────────────────────────────────────

_MAX_RETRIES = 3
_RETRY_DELAY_MS = 100  # Espera inicial entre reintentos (se duplica cada vez)


async def _run_with_retry(coro_factory, max_retries: int = _MAX_RETRIES):
    """Ejecuta una coroutine con reintentos ante fallos transitorios.

    Args:
        coro_factory: Callable async que crea y retorna la coroutine a ejecutar.
        max_retries: Número máximo de reintentos.

    Returns:
        Resultado de la coroutine si tiene éxito.

    Raises:
        La última excepción si se agotan los reintentos.
    """
    for attempt in range(1, max_retries + 1):
        try:
            return await coro_factory()
        except (ConnectionError, TimeoutError) as e:
            if attempt == max_retries:
                logger.error(
                    "  ❌ Se agotaron los reintentos (%d/%d): %s",
                    attempt,
                    max_retries,
                    e,
                )
                raise
            delay = _RETRY_DELAY_MS * (2 ** (attempt - 1)) / 1000
            logger.warning(
                "  ⚠️  Intento %d/%d falló por error transitorio: %s. "
                "Reintentando en %.1fs...",
                attempt,
                max_retries,
                e,
                delay,
            )
            await asyncio.sleep(delay)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _format_doc_context(state: "AgentState") -> str:
    """Construye el contexto que recibe el agente con los docs y chunks disponibles.

    #33 — Incluye los IDs de chunks disponibles para que el agente pueda
    referenciarlos explícitamente en su razonamiento.
    """
    n_docs = len(state.get("document_ids", []))
    n_chunks = len(state.get("chunks", []))
    doc_list = "\n".join(
        f"  - Documento {i + 1}: id={doc_id}"
        for i, doc_id in enumerate(state.get("document_ids", []))
    )

    # #33 — Listar chunks disponibles con sus IDs
    chunks = state.get("chunks", [])
    if chunks:
        chunk_list = "\n".join(
            f"  - Chunk {c.get('chunk_index', i)}: "
            f"chroma_id={c.get('chroma_id', 'N/A')}, "
            f"tokens={c.get('token_count', 0)}, "
            f"doc_id={c.get('doc_id', 'N/A')}"
            for i, c in enumerate(chunks[:20])  # Limitar a 20 para no saturar
        )
        if len(chunks) > 20:
            chunk_list += f"\n  ... y {len(chunks) - 20} chunks m\u00e1s"
    else:
        chunk_list = "  (ninguno)"

    return (
        f"Documentos cargados: {n_docs}\n"
        f"{doc_list}\n"
        f"Chunks generados: {n_chunks}\n"
        f"{chunk_list}\n\n"
        f"REGLAS:\n"
        f"1. Cada sugerencia debe referenciar OBLIGATORIAMENTE el(s) chroma_id(s) "
        f"de los chunks que respaldan la evidencia.\n"
        f"2. Incluye los IDs en el campo 'reasoning' de suggest_update.\n"
        f"3. Respuestas sin source_chunk_ids v\u00e1lidos ser\u00e1n rechazadas."
    )


def _validate_suggestion_fields(args: dict) -> None:
    """Valida campos requeridos de sugerencia (wrapper para compatibilidad).

    Delega en validate_suggestion_data() de guardrails. Convierte
    SuggestionDataValidationError a ToolOutputValidationError para mantener
    compatibilidad con el manejo de errores existente en generate_suggestions_node.

    Raises:
        ToolOutputValidationError: Si falta algún campo requerido.
    """
    try:
        validate_suggestion_data(args)
    except SuggestionDataValidationError as e:
        raise ToolOutputValidationError(str(e)) from e


# ── Nodo 1: load_documents_node ──────────────────────────────────────────────


async def load_documents_node(state: "AgentState") -> dict:
    """Carga documentos curated con status needs_review desde Postgres.

    Solo procesa documentos con category=curated (los reference se
    procesan por separado vía process_reference_documents).
    Marca los documentos como 'processing' para evitar
    que otro worker los procese concurrentemente.
    """
    logger.info("=" * 50)
    logger.info("📂 load_documents_node — buscando documentos pendientes")
    logger.info("=" * 50)

    max_docs = getattr(settings, "MAX_DOCS_PER_CURATION", 20)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Document)
            .where(Document.status == DocumentStatus.needs_review)
            .where(Document.category == DocumentCategory.curated)
            .limit(max_docs)
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
        logger.info(
            "  ✅ Cargados %d documentos (límite: %d): %s",
            len(doc_ids),
            max_docs,
            doc_ids,
        )
        return {"document_ids": doc_ids, "error": None}


# ── Nodo 2: chunk_and_embed_node ─────────────────────────────────────────────


async def _process_single_document(
    db: AsyncSession,
    doc_id_str: str,
) -> tuple[list[dict], dict[str, str], str | None]:
    """Procesa un único documento: parsea, chunkea y embebe.

    Returns:
        Tuple (chunks, documents_text_entry, error).
        Si hay error, chunks y documents_text_entry vienen vacíos.
    """
    try:
        doc_uuid = uuid.UUID(doc_id_str)
        result = await db.execute(select(Document).where(Document.id == doc_uuid))
        doc = result.scalar_one_or_none()

        if not doc:
            return [], {}, f"Documento {doc_id_str} no encontrado en DB"

        file_path = Path(doc.file_path)
        if not file_path.exists():
            return [], {}, f"Archivo no encontrado: {file_path}"

        logger.info("  📄 Procesando: %s (%s)", doc.original_filename, doc.file_type)

        # 1. Parsear
        text = parse_document(str(file_path))
        documents_text_entry = {doc_id_str: text}
        logger.info("     Texto extraído: %d caracteres", len(text))

        # 2. Chunk + embed
        # Determinar categoría para metadata en ChromaDB
        doc_category = doc.category.value if hasattr(doc, "category") else "curated"

        chunk_results = embed_chunks(
            text=text,
            doc_id=doc_id_str,
            category=doc_category,
        )
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

        await db.flush()
        logger.info("  ✅ Documento %s procesado exitosamente", doc_id_str)
        return chunk_results, documents_text_entry, None

    except Exception as e:
        logger.error("  ❌ Error procesando documento %s: %s", doc_id_str, e)
        return [], {}, f"{doc_id_str}: {e}"


async def chunk_and_embed_node(state: "AgentState") -> dict:
    """Parsea, chunkea y embebe cada documento pendiente.

    Para cada documento:
      1. Lee el archivo del disco
      2. Extrae texto plano vía parser.py
      3. Chunk + embedding vía rag/embeddings.py
      4. Persiste los chunks en document_chunks (Postgres)
      5. Almacena el texto extraído en state['documents_text']

    Los documentos se procesan en paralelo usando asyncio.gather
    para mejorar el throughput con múltiples documentos.
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
        tasks = [_process_single_document(db, doc_id_str) for doc_id_str in doc_ids]
        results = await asyncio.gather(*tasks)

        for chunks, text_entry, error in results:
            if error:
                errors.append(error)
            else:
                all_chunks.extend(chunks)
                documents_text.update(text_entry)

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


async def redundancy_detection_node(state: "AgentState") -> dict:
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
                finding = {
                    "chunk_id_a": pair.chunk_id_a,
                    "chunk_id_b": pair.chunk_id_b,
                    "similarity": pair.similarity,
                    "confidence_score": pair.confidence_score,
                    "doc_id_a": pair.doc_id_a,
                    "doc_id_b": pair.doc_id_b,
                    "content_a_preview": pair.content_a_preview,
                    "content_b_preview": pair.content_b_preview,
                    "token_count_a": pair.token_count_a,
                    "token_count_b": pair.token_count_b,
                }
                # Validar contra schema estricto antes de agregar al estado
                try:
                    validate_redundancy_finding(finding)
                    all_findings.append(finding)
                except SuggestionDataValidationError as e:
                    logger.warning(
                        "  ⚠️  Hallazgo de redundancia inválido omitido: %s",
                        e,
                    )

        logger.info(
            "  ✅ Redundancia: %d pares válidos de %d totales",
            len(all_findings),
            sum(len(r.redundant_pairs) for r in reports),
        )
        return {"redundancy_findings": all_findings}

    except Exception as e:
        logger.error("  ❌ Error detectando redundancias: %s", e)
        return {"redundancy_findings": []}


async def inconsistency_detection_node(state: "AgentState") -> dict:
    """Detecta inconsistencias internas y terminológicas en los chunks.

    Ejecuta los cuatro subtipos de detección:
    - self_contradiction: Auto-contradicción intra-documento
    - terminology: Terminología inconsistente entre documentos
    - numerical: Valores numéricos contradictorios
    - structural: Inconsistencias de formato/estructura

    Los subtipos self_contradiction y terminology requieren LLM.
    Sin LLM configurado, solo se ejecutan numerical y structural.
    """
    logger.info("=" * 50)
    logger.info("🔍 inconsistency_detection_node — detectando inconsistencias")
    logger.info("=" * 50)

    chunks = state.get("chunks", [])
    if not chunks:
        logger.info("  ℹ️  No hay chunks para analizar")
        return {"inconsistency_findings": [], "terminology_map": {}}

    from app.rag.inconsistencies import detect_all_inconsistencies

    try:
        # Verificar si hay LLM disponible
        llm = _get_llm_for_node()
        enable_llm = llm is not None

        existing_terminology = state.get("terminology_map", {})

        findings, updated_terminology = await detect_all_inconsistencies(
            chunks=chunks,
            terminology_map=existing_terminology,
            enable_llm=enable_llm,
        )

        # Validar cada hallazgo contra schema estricto
        validated_findings: list[dict] = []
        for finding in findings:
            try:
                validate_inconsistency_finding(finding)
                validated_findings.append(finding)
            except SuggestionDataValidationError as e:
                logger.warning(
                    "  ⚠️  Hallazgo de inconsistencia inválido omitido: %s",
                    e,
                )

        logger.info(
            "  ✅ Inconsistencias: %d hallazgos válidos de %d totales (LLM=%s)",
            len(validated_findings),
            len(findings),
            "sí" if enable_llm else "no",
        )
        return {
            "inconsistency_findings": validated_findings,
            "terminology_map": updated_terminology,
        }

    except Exception as e:
        logger.error("  ❌ Error detectando inconsistencias: %s", e)
        return {"inconsistency_findings": [], "terminology_map": {}}


def _get_llm_for_node():
    """Obtiene el LLM configurado para los nodos."""
    try:
        from app.agents.graph import get_llm

        return get_llm()
    except Exception:
        return None


# ── Nodo 4: agent_node — (se usa directamente create_react_agent como subgraph) ──

# El nodo agent_node y tool_executor_node están encapsulados dentro del subgraph
# que crea create_react_agent() en graph.py. Este archivo solo exporta los nodos
# personalizados del grafo principal.


# ── Nodo 4.5: faq_generation_node ─────────────────────────────────────────────


async def faq_generation_node(state: "AgentState") -> dict:
    """Genera entradas FAQ automáticamente a partir de los chunks del curso.

    Para cada chunk en el estado, invoca generate_faq_entry para producir
    un par pregunta/respuesta y lo persiste como Suggestion con type=faq
    en estado pending.

    El instructor debe aprobar cada FAQ (vía API) antes de que sea oficial.
    """
    logger.info("=" * 50)
    logger.info("❓ faq_generation_node — generando FAQs desde chunks")
    logger.info("=" * 50)

    chunks = state.get("chunks", [])
    if not chunks:
        logger.info("  ℹ️  No hay chunks para generar FAQs")
        return {}

    from app.tools.registry import generate_faq_entry as _generate_faq_entry

    new_suggestions: list[dict] = []
    errors: list[str] = []

    # Límite de chunks que usarán LLM para generar FAQ (por cuota gratuita Gemini: 5 RPM)
    # Los chunks más allá de este límite usarán la heurística de extracción de oraciones
    _MAX_LLM_FAQS = 3
    llm_faq_count = 0
    has_llm = _get_llm_for_node() is not None

    async with AsyncSessionLocal() as db:
        for idx, chunk in enumerate(chunks):
            chunk_id = chunk.get("chroma_id", "")
            chunk_content = chunk.get("text", "")

            # Saltar chunks sin contenido suficiente
            if not chunk_id or len(chunk_content.strip()) < 20:
                continue

            # Extraer document_id del chroma_id (formato: "{uuid}_chunk_{n}")
            doc_id = chunk_id.rsplit("_chunk_", 1)[0] if "_chunk_" in chunk_id else ""
            if not doc_id:
                logger.warning(
                    "  ⚠️  No se pudo extraer doc_id de chroma_id: %s", chunk_id
                )
                continue

            try:
                question = ""
                answer = ""
                # Usar LLM solo para los primeros N chunks; el resto usa heurística
                use_llm = has_llm and llm_faq_count < _MAX_LLM_FAQS
                if use_llm:
                    llm_faq_count += 1

                if use_llm:
                    result_json = await _generate_faq_entry.ainvoke(
                        {
                            "chunk_id": chunk_id,
                            "chunk_content": chunk_content,
                            "topic": "general",
                        }
                    )
                    payload = json.loads(result_json)

                    if payload.get("status") != "success":
                        logger.warning(
                            "  ⚠️  generate_faq_entry falló para chunk %s: %s",
                            chunk_id,
                            payload.get("error", "unknown error"),
                        )
                        # Fallback a heurística
                        use_llm = False
                    else:
                        faq = payload.get("faq", {})
                        question = faq.get("question", "")
                        answer = faq.get("answer", "")

                if not use_llm:
                    # Heurística directa (sin LLM) para no exceder cuota
                    import re

                    sentences = re.split(r"(?<=[.!?])\s+", chunk_content.strip())
                    sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
                    if not sentences:
                        logger.warning(
                            "  ⚠️  Chunk %s sin contenido suficiente, saltando",
                            chunk_id,
                        )
                        continue
                    best_sentence = max(sentences, key=len)
                    other_content = [s for s in sentences if s != best_sentence]

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

                if not question or not answer:
                    logger.warning(
                        "  ⚠️  FAQ vacía generada para chunk %s, saltando",
                        chunk_id,
                    )
                    continue

                # Crear Suggestion type=faq en estado pending
                doc_uuid = uuid.UUID(doc_id)
                description = f"Pregunta: {question}"
                reasoning_text = f"Respuesta: {answer}"

                suggestion = Suggestion(
                    document_id=doc_uuid,
                    type=SuggestionType.faq,
                    description=description,
                    source_doc_id=doc_id,
                    source_chunk_ids=[chunk_id],
                    confidence_score=0.85,
                    reasoning=reasoning_text,
                    status=SuggestionStatus.pending,
                )
                db.add(suggestion)
                await db.flush()

                suggestion_data = {
                    "id": str(suggestion.id),
                    "document_id": doc_id,
                    "type": "faq",
                    "description": description,
                    "confidence_score": 0.85,
                    "question": question,
                    "answer": answer,
                }
                new_suggestions.append(suggestion_data)
                logger.info(
                    "  ✅ FAQ generada: chunk=%s | Q: %s",
                    chunk_id,
                    question[:60],
                )

            except (json.JSONDecodeError, ValueError) as e:
                errors.append(f"Chunk {chunk_id}: error de parseo: {e}")
                logger.warning(
                    "  ⚠️  Error parseando FAQ para chunk %s: %s", chunk_id, e
                )
            except Exception as e:
                errors.append(f"Chunk {chunk_id}: {e}")
                logger.warning(
                    "  ⚠️  Error generando FAQ para chunk %s: %s", chunk_id, e
                )

        await db.commit()

    if errors:
        logger.warning(
            "  ⚠️  Errores parciales generando FAQs (%d): %s",
            len(errors),
            "; ".join(errors[:3]),
        )

    logger.info("  📊 FAQs generadas: %d", len(new_suggestions))

    # Combinar con sugerencias existentes del estado
    existing = state.get("suggestions", [])
    return {"suggestions": existing + new_suggestions}


# ── Nodo 4.75: web_search_node ────────────────────────────────────────────────


async def web_search_node(state: "AgentState") -> dict:
    """Ejecuta búsquedas web para validar datos factuales y enriquecer sugerencias.

    Analiza los chunks disponibles, genera consultas relevantes y
    almacena los resultados en web_search_results para que el
    react_agent los use como evidencia complementaria.

    Los resultados web NUNCA reemplazan fuentes documentales;
    se marcan explícitamente con source_type="web".
    """
    logger.info("=" * 50)
    logger.info("🌐 web_search_node — buscando información web complementaria")
    logger.info("=" * 50)

    chunks = state.get("chunks", [])
    if not chunks:
        logger.info("  ℹ️  No hay chunks para generar consultas web")
        return {"web_search_results": []}

    # Generar consultas relevantes desde el contenido de los chunks
    topics = set()
    for chunk in chunks[:5]:
        text = chunk.get("text", "") or chunk.get("content", "")
        if text and len(text.strip()) > 30:
            first_bit = text.split(".")[0].strip()
            if len(first_bit) > 20:
                topics.add(first_bit[:120])

    queries = list(topics)[:3]
    if not queries:
        logger.info("  ℹ️  No se generaron consultas web del contenido")
        return {"web_search_results": []}

    logger.info("  📋 Consultas a ejecutar: %d", len(queries))

    from app.tools.registry import search_web as search_web_tool

    max_results = settings.WEB_SEARCH_MAX_RESULTS
    all_results: list[dict] = []

    for query in queries:
        try:
            result_json = await search_web_tool.ainvoke(
                {
                    "query": query,
                    "max_results": max_results,
                }
            )
            payload = json.loads(result_json)
            if payload.get("status") == "success":
                all_results.extend(payload.get("results", []))
                logger.info(
                    "  ✅ Búsqueda: '%s' → %d resultados",
                    query[:50],
                    len(payload.get("results", [])),
                )
            else:
                logger.warning(
                    "  ⚠️  Búsqueda falló '%s': %s",
                    query[:50],
                    payload.get("error", ""),
                )
        except Exception as e:
            logger.error("  ❌ Error en búsqueda '%s': %s", query[:50], e)

    logger.info("  📊 Resultados web recolectados: %d", len(all_results))
    return {"web_search_results": all_results}


# ── Nodo 5: generate_suggestions_node ────────────────────────────────────────


async def generate_suggestions_node(state: "AgentState") -> dict:
    """Procesa las respuestas del agente y crea sugerencias en Postgres.

    También procesa los hallazgos de redundancia e inconsistencia detectados
    automáticamente, creando sugerencias de tipo 'redundancy' y 'conflict'
    respectivamente.

    Flujo:
      1. Procesa tool calls de suggest_update del agente ReAct
      2. Procesa redundancy_findings del nodo de detección automática
      3. Procesa inconsistency_findings del nodo de detección automática
      4. Persiste todo en Postgres con estado 'pending'
    """
    logger.info("=" * 50)
    logger.info("💡 generate_suggestions_node — generando sugerencias")
    logger.info("=" * 50)

    suggestions: list[dict] = []
    messages = state.get("messages", [])
    redundancy_findings = state.get("redundancy_findings", [])
    inconsistency_findings = state.get("inconsistency_findings", [])

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
                            # #33 — Incluir evidencia de chunks en tracking
                            "source_doc_id": payload.get("source_doc_id", ""),
                            "source_chunk_ids": payload.get("source_chunk_ids", []),
                        }
                    )
                    logger.info(
                        "  ✅ Sugerencia del agente registrada por tool: %s "
                        "(chunks: %s, doc: %s)",
                        payload["suggestion_id"],
                        payload.get("source_chunk_ids", []),
                        payload.get("source_doc_id", ""),
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
                content_a_preview = finding.get("content_a_preview", "")
                content_b_preview = finding.get("content_b_preview", "")
                token_count_a = finding.get("token_count_a", 0)
                token_count_b = finding.get("token_count_b", 0)

                reasoning = (
                    f"Detección automática de redundancia:\n"
                    f"- Chunk A: {chunk_id_a} (documento: {doc_id_a})\n"
                    f"- Chunk B: {chunk_id_b} (documento: {doc_id_b})\n"
                    f"- Similitud coseno: {similarity:.4f}\n"
                    f"- Confidence score: {confidence:.4f}\n"
                    f"- Threshold usado: {settings.REDUNDANCY_THRESHOLD}\n"
                    f"- Tokens chunk A: {token_count_a} | Tokens chunk B: {token_count_b}\n"
                )
                if content_a_preview:
                    reasoning += f'- Preview A: "{content_a_preview[:150]}..."\n'
                if content_b_preview:
                    reasoning += f'- Preview B: "{content_b_preview[:150]}..."\n'

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

        # ── 3. Procesar hallazgos de inconsistencia automática ───────────────
        for finding in inconsistency_findings:
            try:
                inc_type = finding.get("type", "conflict")
                severity = finding.get("severity", "medium")
                chunk_id_a = finding.get("chunk_id_a", "")
                chunk_id_b = finding.get("chunk_id_b", "")
                doc_id_a = finding.get("doc_id_a", "")
                doc_id_b = finding.get("doc_id_b", doc_id_a)
                extract_a = finding.get("extract_a", "")
                extract_b = finding.get("extract_b", "")
                description = finding.get("description", "")
                suggestion_text = finding.get("suggestion", "")

                if not doc_id_a:
                    continue

                doc_uuid = uuid.UUID(doc_id_a)

                # Construir source_chunk_ids para la sugerencia
                source_chunks = []
                if chunk_id_a:
                    source_chunks.append(chunk_id_a)
                if chunk_id_b and chunk_id_b != chunk_id_a:
                    source_chunks.append(chunk_id_b)

                # Mapa de severidad a score de confianza
                severity_confidence = {
                    "high": 0.85,
                    "medium": 0.65,
                    "low": 0.40,
                }
                confidence = severity_confidence.get(severity, 0.5)

                type_label_map = {
                    "self_contradiction": "Auto-contradicción",
                    "terminology": "Terminología inconsistente",
                    "numerical": "Valor numérico contradictorio",
                    "structural": "Inconsistencia estructural",
                }
                type_label = type_label_map.get(inc_type, inc_type)

                full_description = (
                    f"[{type_label}] {description}\n\nFragmento A: {extract_a[:200]}\n"
                )
                if extract_b:
                    full_description += f"Fragmento B: {extract_b[:200]}\n"
                full_description += f"\nSugerencia: {suggestion_text}"

                reasoning = (
                    f"Detección automática de inconsistencia:\n"
                    f"- Tipo: {inc_type}\n"
                    f"- Severidad: {severity}\n"
                    f"- Documento A: {doc_id_a}\n"
                    f"- Documento B: {doc_id_b}\n"
                    f"- Chunk A: {chunk_id_a}\n"
                    f"- Chunk B: {chunk_id_b}\n"
                    f"- Extracto A: {extract_a[:300]}...\n"
                )
                if extract_b:
                    reasoning += f"- Extracto B: {extract_b[:300]}...\n"
                reasoning += f"- Acción sugerida: {suggestion_text}"

                suggestion = Suggestion(
                    document_id=doc_uuid,
                    type=SuggestionType.conflict,
                    description=full_description,
                    source_doc_id=doc_id_a,
                    source_chunk_ids=source_chunks,
                    confidence_score=confidence,
                    reasoning=reasoning,
                    status=SuggestionStatus.pending,
                )
                db.add(suggestion)
                await db.flush()

                suggestion_data = {
                    "id": str(suggestion.id),
                    "document_id": doc_id_a,
                    "type": "conflict",
                    "description": full_description,
                    "confidence_score": confidence,
                }
                suggestions.append(suggestion_data)
                logger.info(
                    "  ✅ Sugerencia inconsistencia: %s (tipo=%s, severidad=%s)",
                    suggestion.id,
                    inc_type,
                    severity,
                )

            except Exception as e:
                logger.error("  ❌ Error creando sugerencia de inconsistencia: %s", e)

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


async def wait_human_approval_node(state: "AgentState") -> dict:
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
