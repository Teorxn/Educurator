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
import re
import uuid
from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage
from sqlalchemy import select

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

    Si la corrida trae document_ids explícitos (p. ej. auto-curación al
    subir UN documento), se procesan SOLO esos — sin este filtro, cada
    upload reprocesaba todos los documentos pendientes del sistema.
    Sin ids explícitos, busca todos los needs_review (corrida global).

    Solo procesa documentos con category=curated (los reference se
    procesan por separado vía process_reference_documents).
    Marca los documentos como 'processing' para evitar
    que otro worker los procese concurrentemente.
    """
    logger.info("=" * 50)
    logger.info("📂 load_documents_node — buscando documentos pendientes")
    logger.info("=" * 50)

    max_docs = getattr(settings, "MAX_DOCS_PER_CURATION", 20)
    requested_ids = state.get("document_ids") or []

    async with AsyncSessionLocal() as db:
        query = (
            select(Document)
            .where(Document.status == DocumentStatus.needs_review)
            .where(Document.category == DocumentCategory.curated)
            .limit(max_docs)
        )
        if requested_ids:
            requested_uuids = []
            for rid in requested_ids:
                try:
                    requested_uuids.append(uuid.UUID(rid))
                except ValueError:
                    logger.warning("  ⚠️  document_id inválido ignorado: %s", rid)
            query = query.where(Document.id.in_(requested_uuids))
            logger.info(
                "  🎯 Corrida acotada a %d documento(s) solicitados",
                len(requested_uuids),
            )

        result = await db.execute(query)
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
    doc_id_str: str,
) -> tuple[list[dict], dict[str, str], str | None]:
    """Procesa un único documento: parsea, chunkea y embebe.

    Abre su propia AsyncSession — las sesiones de SQLAlchemy NO son seguras
    para uso concurrente, por lo que cada tarea paralela necesita la suya.
    El parseo y el embedding (CPU-bound) corren en un thread para no
    bloquear el event loop.

    Returns:
        Tuple (chunks, documents_text_entry, error).
        Si hay error, chunks y documents_text_entry vienen vacíos.
    """
    try:
        doc_uuid = uuid.UUID(doc_id_str)
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Document).where(Document.id == doc_uuid))
            doc = result.scalar_one_or_none()

            if not doc:
                return [], {}, f"Documento {doc_id_str} no encontrado en DB"

            file_path = Path(doc.file_path)
            if not file_path.exists():
                return [], {}, f"Archivo no encontrado: {file_path}"

            logger.info(
                "  📄 Procesando: %s (%s)", doc.original_filename, doc.file_type
            )

            # 1. Parsear (en thread: I/O + CPU-bound)
            text = await asyncio.to_thread(parse_document, str(file_path))
            documents_text_entry = {doc_id_str: text}
            logger.info("     Texto extraído: %d caracteres", len(text))

            # 2. Chunk + embed (en thread: sentence-transformers es CPU-bound)
            # Determinar categoría para metadata en ChromaDB
            doc_category = doc.category.value if hasattr(doc, "category") else "curated"

            chunk_results = await asyncio.to_thread(
                embed_chunks,
                text=text,
                doc_id=doc_id_str,
                category=doc_category,
            )
            logger.info("     Chunks generados: %d", len(chunk_results))

            # 3. Persistir chunks en Postgres (reprocesamiento idempotente:
            # si una corrida anterior murió a medias —timeout, crash— sus
            # chunks ya commiteados se reemplazan en vez de duplicarse)
            from sqlalchemy import delete as sa_delete

            deleted = await db.execute(
                sa_delete(DocumentChunk).where(
                    DocumentChunk.document_id == doc_uuid
                )
            )
            if deleted.rowcount:
                logger.info(
                    "     🧹 Reemplazando %d chunks de una corrida anterior",
                    deleted.rowcount,
                )

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

            await db.commit()
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

    Los documentos se procesan en paralelo usando asyncio.gather,
    con concurrencia acotada (EMBED_CONCURRENCY) y una sesión de DB
    independiente por documento (las AsyncSession no admiten uso concurrente).
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

    semaphore = asyncio.Semaphore(max(1, getattr(settings, "EMBED_CONCURRENCY", 4)))

    async def _bounded(doc_id_str: str):
        async with semaphore:
            return await _process_single_document(doc_id_str)

    tasks = [_bounded(doc_id_str) for doc_id_str in doc_ids]
    results = await asyncio.gather(*tasks)

    for chunks, text_entry, error in results:
        if error:
            errors.append(error)
        else:
            all_chunks.extend(chunks)
            documents_text.update(text_entry)

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

    new_suggestions: list[dict] = []
    errors: list[str] = []

    # Límite de chunks que reciben FAQ del LLM; el resto usa heurística.
    # OPTIMIZACIÓN: todas las FAQs con LLM se generan en UNA sola llamada
    # (batch) — con el rate limiter de Gemini a 4 RPM, N llamadas separadas
    # cuestan ~15s de fila cada una.
    _MAX_LLM_FAQS = 3
    has_llm = _get_llm_for_node() is not None
    run_doc_ids = set(state.get("document_ids", []))

    # ── 1. Selección de candidatos (validaciones antes de tocar LLM/DB) ───
    eligible: list[dict] = []
    for chunk in chunks:
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

        # Guarda: solo generar FAQs para documentos de ESTA corrida.
        # Un chroma_id ajeno (p. ej. de un documento borrado que quedó
        # en el vector store) provocaría un FK violation al persistir.
        if run_doc_ids and doc_id not in run_doc_ids:
            logger.warning(
                "  ⚠️  Chunk %s pertenece a un documento fuera de la corrida "
                "(%s) — se omite",
                chunk_id,
                doc_id,
            )
            continue

        eligible.append(
            {"chunk_id": chunk_id, "content": chunk_content, "doc_id": doc_id}
        )

    logger.info(
        "  ⚙️  Config FAQ: LLM %s | %d chunks elegibles | máx. %d vía LLM "
        "(en 1 llamada batch), resto heurística",
        "disponible" if has_llm else "NO disponible (solo heurística)",
        len(eligible),
        _MAX_LLM_FAQS,
    )

    # ── 2. UNA llamada batch al LLM para los primeros N chunks ────────────
    batch_results: dict[str, tuple[str, str]] = {}
    if has_llm and eligible:
        from app.tools.registry import generate_faqs_batch_with_llm

        llm_items = [
            (e["chunk_id"], e["content"]) for e in eligible[:_MAX_LLM_FAQS]
        ]
        batch_results = await generate_faqs_batch_with_llm(llm_items)

    # ── 3. Persistencia (heurística para los chunks sin resultado batch) ──
    async with AsyncSessionLocal() as db:
        for item in eligible:
            chunk_id = item["chunk_id"]
            chunk_content = item["content"]
            doc_id = item["doc_id"]

            try:
                question = ""
                answer = ""
                generation_method = "heuristic"

                if chunk_id in batch_results:
                    question, answer = batch_results[chunk_id]
                    generation_method = "llm"

                if generation_method == "heuristic":
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

                # Confianza diferenciada por método de generación:
                #   - LLM: 0.85 (respuesta redactada por el modelo)
                #   - heurística: 0.60 (extracción de oraciones, menor calidad)
                confidence = 0.85 if generation_method == "llm" else 0.60

                # Crear Suggestion type=faq en estado pending
                doc_uuid = uuid.UUID(doc_id)
                description = f"Pregunta: {question}"
                reasoning_text = (
                    f"Respuesta: {answer}\n\n"
                    f"[Generación: {'LLM' if generation_method == 'llm' else 'heurística de oraciones'} "
                    f"| confianza: {confidence:.2f}]"
                )

                suggestion = Suggestion(
                    document_id=doc_uuid,
                    type=SuggestionType.faq,
                    description=description,
                    source_doc_id=doc_id,
                    source_chunk_ids=[chunk_id],
                    confidence_score=confidence,
                    reasoning=reasoning_text,
                    status=SuggestionStatus.pending,
                )
                db.add(suggestion)
                # Commit por FAQ (expire_on_commit=False): si una fila
                # posterior falla, las FAQs ya persistidas no se pierden.
                await db.commit()

                suggestion_data = {
                    "id": str(suggestion.id),
                    "document_id": doc_id,
                    "type": "faq",
                    "description": description,
                    "confidence_score": confidence,
                    "question": question,
                    "answer": answer,
                    "generation_method": generation_method,
                }
                new_suggestions.append(suggestion_data)
                logger.info(
                    "  ✅ FAQ generada (%s, confianza %.2f): chunk=%s | Q: %s",
                    generation_method,
                    confidence,
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
                # Un flush fallido (p. ej. FK violation) envenena la sesión:
                # sin rollback, TODOS los flush/commit posteriores fallarían
                # con PendingRollbackError y se perderían las FAQs válidas.
                try:
                    await db.rollback()
                except Exception:
                    pass

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

# Líneas que NO sirven como consulta web: encabezados de formatos
# institucionales, códigos de documento, numeraciones, fechas sueltas
_WEB_QUERY_NOISE = re.compile(
    r"^\s*("
    r"c[oó]digo\s*[:.]|versi[oó]n\s+\d|formato\s|p[aá]gina\s+\d|fecha\s*[:.]|"
    r"[A-Z]{2,}-[A-Z]{2,}-\d|"  # códigos tipo GDC-FR-15
    r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"  # fechas
    r"tabla\s+de\s+contenido|índice"
    r")",
    re.IGNORECASE,
)


def _clean_filename_query(filename: str) -> str:
    """Convierte un nombre de archivo en consulta web ('mi_doc v2.pdf' → 'mi doc')."""
    stem = re.sub(r"\.[a-z0-9]{2,5}$", "", filename, flags=re.IGNORECASE)
    stem = re.sub(r"[_\-.]+", " ", stem)
    # Quitar sufijos de versionado que no aportan a la búsqueda
    stem = re.sub(
        r"\b(v\d+|versi[oó]n\s*\d*|final|original|act\w*|copia)\b",
        "",
        stem,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s{2,}", " ", stem).strip()


def _pick_content_sentence(chunks: list[dict]) -> str:
    """Elige la oración más informativa de los primeros chunks como consulta.

    Filtra encabezados de formatos, códigos y numeraciones (el bug clásico:
    buscar 'Código: GDC-FR-15 Versión 004' en la web no aporta nada).
    """
    candidates: list[str] = []
    for chunk in chunks[:3]:
        text = chunk.get("text", "") or chunk.get("content", "")
        for sentence in re.split(r"(?<=[.!?:\n])\s+", text):
            # Normalizar espacios/saltos de línea internos
            s = re.sub(r"\s+", " ", sentence).strip()
            if not (40 <= len(s) <= 140):
                continue
            if _WEB_QUERY_NOISE.search(s):
                continue
            # Debe ser mayormente texto (no tablas/números sueltos)
            letters = sum(c.isalpha() or c.isspace() for c in s)
            if letters / len(s) < 0.75:
                continue
            candidates.append(s)
    if not candidates:
        return ""
    # La más larga dentro del rango suele ser la más descriptiva
    return max(candidates, key=len)[:120]


async def _build_web_queries(state: "AgentState") -> list[str]:
    """Construye hasta 2 consultas web de calidad para la corrida.

    1. El nombre del documento (limpio): suele describir el tema exacto.
    2. La oración más informativa del contenido (filtrando encabezados).
    """
    queries: list[str] = []

    # Consulta 1: nombre(s) de documento de la corrida
    doc_ids = state.get("document_ids", [])
    if doc_ids:
        try:
            doc_uuids = [uuid.UUID(d) for d in doc_ids[:3]]
            async with AsyncSessionLocal() as db:
                rows = (
                    await db.execute(
                        select(Document.original_filename).where(
                            Document.id.in_(doc_uuids)
                        )
                    )
                ).all()
            for (fname,) in rows:
                q = _clean_filename_query(fname or "")
                if len(q) >= 15 and q not in queries:
                    queries.append(q)
                if len(queries) >= 1:  # 1 consulta por nombre basta
                    break
        except Exception as e:
            logger.warning("  ⚠️  No se pudieron leer nombres de documentos: %s", e)

    # Consulta 2: oración representativa del contenido
    sentence = _pick_content_sentence(state.get("chunks", []))
    if sentence and sentence not in queries:
        queries.append(sentence)

    return queries[:2]


async def web_search_node(state: "AgentState") -> dict:
    """Busca información web para validar y enriquecer el análisis del agente.

    Genera hasta 2 consultas de CALIDAD (nombre del documento + oración
    representativa, filtrando encabezados de formatos) y guarda los
    mejores resultados en web_search_results. El nodo react_agent los
    recibe como evidencia complementaria en su contexto y puede citarlos
    vía source_web_url en suggest_update.

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

    queries = await _build_web_queries(state)
    if not queries:
        logger.info("  ℹ️  No se generaron consultas web de calidad — se omite")
        return {"web_search_results": []}

    logger.info("  📋 Consultas a ejecutar: %d", len(queries))
    for q in queries:
        logger.info("     🔎 '%s'", q[:90])

    from app.tools.registry import search_web as search_web_tool

    max_results = settings.WEB_SEARCH_MAX_RESULTS
    all_results: list[dict] = []

    for q_idx, query in enumerate(queries):
        # Pausa entre consultas: DDG bloquea ráfagas consecutivas con 202
        if q_idx > 0:
            logger.info("  ⏸️  Pausa de 2s entre consultas (anti rate-limit)")
            await asyncio.sleep(2)
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
                error_text = str(payload.get("error", ""))
                logger.warning(
                    "  ⚠️  Búsqueda falló '%s': %s",
                    query[:50],
                    error_text,
                )
                # Circuit breaker: si el proveedor nos está bloqueando,
                # las siguientes consultas también fallarán — abortar ya
                # evita desperdiciar tiempo en reintentos inútiles.
                if "ratelimit" in error_text.lower() or "429" in error_text:
                    logger.warning(
                        "  🔌 Proveedor de búsqueda con rate limit — "
                        "se omiten las consultas restantes"
                    )
                    break
        except Exception as e:
            logger.error("  ❌ Error en búsqueda '%s': %s", query[:50], e)

    # Dedupe por URL y cap: el agente recibirá los primeros como contexto
    seen_urls: set[str] = set()
    unique_results: list[dict] = []
    for r in all_results:
        url = r.get("url", "")
        if url and url in seen_urls:
            continue
        seen_urls.add(url)
        unique_results.append(r)
    unique_results = unique_results[:6]

    logger.info(
        "  📊 Resultados web recolectados: %d (únicos: %d)",
        len(all_results),
        len(unique_results),
    )
    return {"web_search_results": unique_results}


# ── Nodo 4.8: reference_comparison_node ──────────────────────────────────────


async def reference_comparison_node(state: "AgentState") -> dict:
    """Compara el contenido del curso contra el corpus de REFERENCIA.

    Para cada chunk curado de la corrida, recupera los fragmentos de
    referencia más similares (ChromaDB, metadata category=reference) y,
    en UNA llamada al LLM, evalúa si el contenido cumple lo que dicen las
    referencias (buenas prácticas, lineamientos, normativas). Las
    desviaciones se persisten como sugerencias type=update con el
    documento de referencia como fuente (la UI muestra el badge
    '📚 Fuente: Referencia' y la evidencia de ambos fragmentos).

    Requiere LLM; sin él, el nodo se omite (comparar semánticamente
    curso↔referencia sin modelo produce falsos positivos).
    """
    logger.info("=" * 50)
    logger.info("📚 reference_comparison_node — validando contra referencias")
    logger.info("=" * 50)

    chunks = state.get("chunks", [])
    if not chunks:
        logger.info("  ℹ️  No hay chunks para comparar")
        return {}

    if _get_llm_for_node() is None:
        logger.info("  ℹ️  Sin LLM — comparación contra referencias omitida")
        return {}

    threshold = getattr(settings, "REFERENCE_SIMILARITY_THRESHOLD", 0.35)
    max_pairs = getattr(settings, "MAX_REFERENCE_PAIRS", 6)
    top_k = getattr(settings, "REFERENCE_TOP_K", 2)
    run_doc_ids = set(state.get("document_ids", []))

    from app.rag.embeddings import get_chroma_collection

    # ── 1. Recuperar referencias similares por cada chunk curado ──────────
    # La similitud se calcula con coseno sobre los embeddings directamente:
    # la colección de Chroma usa espacio L2 por defecto y sus 'distances'
    # no son convertibles a similitud coseno con 1-d.
    def _find_reference_matches() -> list[dict]:
        from app.rag.redundancy import _cosine_similarity

        collection = get_chroma_collection()

        # Corpus de referencia completo (es pequeño; cap defensivo)
        ref_data = collection.get(
            where={"category": "reference"},
            include=["embeddings", "documents", "metadatas"],
            limit=500,
        )
        ref_ids = ref_data.get("ids") or []
        if not ref_ids:
            return []
        ref_embs = ref_data.get("embeddings")
        ref_docs = ref_data.get("documents") or []
        ref_metas = ref_data.get("metadatas") or []

        pairs: list[dict] = []
        for chunk in chunks[:10]:  # cap: documentos enormes no explotan en pares
            chunk_id = chunk.get("chroma_id", "")
            content = chunk.get("text", "")
            if not chunk_id or len(content.strip()) < 30:
                continue

            # Reusar el embedding ya almacenado del chunk curado
            stored = collection.get(ids=[chunk_id], include=["embeddings"])
            embs = stored.get("embeddings")
            if embs is None or len(embs) == 0 or embs[0] is None:
                continue
            cur_emb = embs[0]

            # Coseno contra cada chunk de referencia; top_k por chunk curado
            scored: list[tuple[float, int]] = []
            for j in range(len(ref_ids)):
                ref_emb = ref_embs[j] if ref_embs is not None else None
                if ref_emb is None or len(ref_emb) == 0:
                    continue
                similarity = _cosine_similarity(cur_emb, ref_emb)
                if similarity >= threshold:
                    scored.append((similarity, j))
            scored.sort(reverse=True)

            for similarity, j in scored[:top_k]:
                pairs.append(
                    {
                        "curated_chunk_id": chunk_id,
                        "curated_content": content,
                        "reference_chunk_id": ref_ids[j],
                        "reference_content": ref_docs[j] if j < len(ref_docs) else "",
                        "reference_doc_id": (ref_metas[j] or {}).get("doc_id", "")
                        if j < len(ref_metas)
                        else "",
                        "similarity": round(float(similarity), 4),
                    }
                )

        # Los pares más relevantes primero; cap global para la llamada LLM
        pairs.sort(key=lambda p: p["similarity"], reverse=True)
        return pairs[:max_pairs]

    try:
        pairs = await asyncio.to_thread(_find_reference_matches)
    except Exception as e:
        logger.error("  ❌ Error recuperando referencias: %s", e)
        return {}

    if not pairs:
        logger.info(
            "  ℹ️  Sin corpus de referencia o sin pares relevantes "
            "(threshold=%.2f) — nada que comparar",
            threshold,
        )
        return {}

    logger.info(
        "  🔗 %d pares curso↔referencia relevantes (threshold=%.2f)",
        len(pairs),
        threshold,
    )

    # ── 2. UNA llamada al LLM evalúa todos los pares ───────────────────────
    from app.tools.registry import compare_against_references_with_llm

    recommendations = await compare_against_references_with_llm(pairs)
    if not recommendations:
        logger.info("  ✅ El contenido cumple las referencias — sin sugerencias")
        return {}

    # ── 3. Persistir recomendaciones como sugerencias type=update ─────────
    new_suggestions: list[dict] = []
    async with AsyncSessionLocal() as db:
        for rec in recommendations:
            pair = pairs[rec["pair_index"]]
            curated_chunk_id = pair["curated_chunk_id"]
            doc_id = (
                curated_chunk_id.rsplit("_chunk_", 1)[0]
                if "_chunk_" in curated_chunk_id
                else ""
            )
            if not doc_id or (run_doc_ids and doc_id not in run_doc_ids):
                continue

            try:
                description = f"Recomendación según referencia: {rec['recommendation']}"
                if len(description) > 1900:
                    description = description[:1900] + "…"
                reasoning = (
                    f"{rec.get('reasoning', '')}\n\n"
                    f"[Comparación contra documento de referencia "
                    f"{pair['reference_doc_id']} | similitud semántica: "
                    f"{pair['similarity']:.2f} | evidencia: fragmento del curso "
                    f"{curated_chunk_id} vs referencia {pair['reference_chunk_id']}]"
                )

                suggestion = Suggestion(
                    document_id=uuid.UUID(doc_id),
                    type=SuggestionType.update,
                    description=description,
                    # source_doc_id = documento de REFERENCIA → la API deriva
                    # source_type='reference' y la UI muestra el badge 📚
                    source_doc_id=pair["reference_doc_id"] or doc_id,
                    source_chunk_ids=[
                        curated_chunk_id,
                        pair["reference_chunk_id"],
                    ],
                    confidence_score=rec["confidence"],
                    reasoning=reasoning,
                    status=SuggestionStatus.pending,
                )
                db.add(suggestion)
                await db.commit()

                new_suggestions.append(
                    {
                        "id": str(suggestion.id),
                        "document_id": doc_id,
                        "type": "update",
                        "description": description,
                        "confidence_score": rec["confidence"],
                        "source_type": "reference",
                    }
                )
                logger.info(
                    "  ✅ Recomendación por referencia (conf %.2f): %s",
                    rec["confidence"],
                    rec["recommendation"][:70],
                )
            except Exception as e:
                logger.error("  ❌ Error persistiendo recomendación: %s", e)
                try:
                    await db.rollback()
                except Exception:
                    pass

    existing = state.get("suggestions", [])
    return {"suggestions": existing + new_suggestions}


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
                # Desenvenenar la sesión tras un flush fallido (FK, etc.)
                try:
                    await db.rollback()
                except Exception:
                    pass

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
                # Desenvenenar la sesión tras un flush fallido (FK, etc.)
                try:
                    await db.rollback()
                except Exception:
                    pass

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

    # Conservar las sugerencias ya presentes en el estado (p. ej. las FAQs
    # de faq_generation_node, que corre antes): sin esto se pierden del
    # estado final y los contadores del histórico quedan incompletos.
    existing = state.get("suggestions", [])
    combined = existing + suggestions
    logger.info(
        "  📊 Sugerencias totales: %d (%d previas + %d de este nodo)",
        len(combined),
        len(existing),
        len(suggestions),
    )

    return {"suggestions": combined}


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
