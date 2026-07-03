"""
#12 — Grafo LangGraph compilado con SqliteSaver checkpointer.

Ensambla todos los nodos en un grafo ejecutable end-to-end:
  load_documents → chunk_and_embed → redundancy_detection →
  react_agent (subgraph) → generate_suggestions → wait_human_approval → END

Configuración del LLM (por orden de preferencia):
  1. OpenAI        (si OPENAI_API_KEY válida en .env)
  2. Google Gemini (si GEMINI_API_KEY válida en .env)
  3. Hugging Face  (si HUGGINGFACE_MODEL configurado en .env)
  4. Sin LLM       (solo pipeline RAG, sin agente)

El ReAct agent se crea con create_react_agent de langgraph.prebuilt,
que maneja automáticamente el loop de tool calling.

Uso:
    from app.agents.graph import run_curation
    result = await run_curation(thread_id="curation-run-1")
"""

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import create_react_agent

from app.agents.nodes import (
    chunk_and_embed_node,
    faq_generation_node,
    generate_suggestions_node,
    inconsistency_detection_node,
    load_documents_node,
    redundancy_detection_node,
    wait_human_approval_node,
    web_search_node,
)
from app.agents.state import AgentState
from app.config import settings
from app.tools.registry import get_all_tools

logger = logging.getLogger(__name__)


# ── Langfuse Callback Factory ────────────────────────────────────────────────


def _create_langfuse_handler() -> Optional[Any]:
    """Crea el callback handler de Langfuse si está configurado.

    Retorna None si las credenciales no están configuradas,
    permitiendo que el grafo funcione sin tracing.
    """
    pk = settings.LANGFUSE_PUBLIC_KEY.strip()
    sk = settings.LANGFUSE_SECRET_KEY.strip()
    if not pk or not sk:
        logger.info("ℹ️  Langfuse no configurado — se omite tracing")
        return None

    try:
        from langfuse.callback import CallbackHandler  # type: ignore[import-untyped]

        handler = CallbackHandler(
            secret_key=sk,
            public_key=pk,
            host=settings.LANGFUSE_HOST or "https://cloud.langfuse.com",
        )
        logger.info("✅ Langfuse CallbackHandler configurado")
        return handler
    except ImportError:
        logger.warning("⚠️  langfuse no instalado — se omite tracing")
        return None
    except Exception as e:
        logger.warning("⚠️  Error configurando Langfuse: %s — se omite tracing", e)
        return None


# ── Factory: crear el LLM según configuración ────────────────────────────────


def _create_llm():
    """Crea el modelo de lenguaje según la configuración disponible.

    Orden de preferencia:
      1. OpenAI        (si OPENAI_API_KEY está configurada y no es placeholder)
      2. Google Gemini  (si GEMINI_API_KEY está configurada)
      3. Hugging Face  (si HUGGINGFACE_MODEL está configurado)
      4. None          (modo solo pipeline RAG, sin agente)
    """
    openai_key = (settings.OPENAI_API_KEY or "").strip()
    has_openai = bool(openai_key) and openai_key != "sk-..."

    if has_openai:
        from langchain_openai import ChatOpenAI

        logger.info("Usando OpenAI: gpt-4o-mini")
        return ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0,
            max_retries=settings.LLM_MAX_RETRIES,
        )

    gemini_key = (settings.GEMINI_API_KEY or "").strip()
    if gemini_key:
        try:
            from langchain_core.rate_limiters import InMemoryRateLimiter
            from langchain_google_genai import ChatGoogleGenerativeAI

            # Free tier Gemini: 5 requests/minuto → limitamos a 4 RPM
            # (0.0667 req/s = 1 request cada ~15s)
            rate_limiter = InMemoryRateLimiter(
                requests_per_second=0.06,
                check_every_n_seconds=0.1,
                max_bucket_size=1,  # Sin ráfagas
            )

            gemini_model = (settings.GEMINI_MODEL or "gemini-2.5-flash").strip()
            logger.info(
                "Usando Google Gemini: %s (rate limited: 4 RPM)", gemini_model
            )
            return ChatGoogleGenerativeAI(
                model=gemini_model,
                temperature=0,
                api_key=gemini_key,
                rate_limiter=rate_limiter,
                max_retries=settings.LLM_MAX_RETRIES,
            )
        except Exception as e:
            logger.warning("Error configurando Gemini: %s", e)

    hf_model = (settings.HUGGINGFACE_MODEL or "").strip()
    if hf_model:
        try:
            from langchain_huggingface import ChatHuggingFace, HuggingFacePipeline

            logger.info("Cargando modelo local Hugging Face: %s", hf_model)
            pipeline = HuggingFacePipeline.from_model_id(
                model_id=hf_model,
                task="text-generation",
                pipeline_kwargs={
                    "max_new_tokens": 1024,
                    "temperature": 0.1,
                    "do_sample": True,
                },
                device_map="auto",
            )
            return ChatHuggingFace(llm=pipeline, verbose=False)
        except Exception as e:
            logger.warning("Error cargando modelo Hugging Face: %s", e)

    logger.warning(
        "⚠️  No hay LLM configurado. "
        "Define OPENAI_API_KEY, GEMINI_API_KEY o HUGGINGFACE_MODEL en .env.\n"
        "  Ejemplos:\n"
        "    GEMINI_API_KEY=tu-api-key\n"
        "    HUGGINGFACE_MODEL=TinyLlama/TinyLlama-1.1B-Chat-v1.0\n"
        "  El grafo se usará sin agente (solo pipeline RAG)."
    )
    return None


# ── Config global ────────────────────────────────────────────────────────────

_LLM = _create_llm()
_TOOLS = get_all_tools()


def get_llm():
    """Retorna el LLM configurado (puede ser None si no hay proveedor).

    Útil para tools que quieran usar el LLM opcionalmente
    (ej: generate_faq_entry para mejorar calidad de FAQs).
    """
    return _LLM


# ── System prompt del agente ─────────────────────────────────────────────────

_SYSTEM_PROMPT = SystemMessage(
    content=(
        "Eres un asistente de curación de contenido educativo universitario. "
        "Tu función es analizar documentos de cursos para mejorar su calidad y coherencia.\n\n"
        "TUS TAREAS:\n"
        "1. Revisar el contenido de los documentos y sus chunks\n"
        "2. Detectar información redundante entre documentos\n"
        "3. Identificar contradicciones o conflictos de información\n"
        "4. Generar preguntas frecuentes (FAQs) basadas en el contenido\n"
        "5. Sugerir mejoras o actualizaciones cuando sea necesario\n\n"
        "REGLAS ESTRICTAS:\n"
        "- NUNCA modifiques contenido oficial directamente\n"
        "- Usa suggest_update para crear sugerencias en estado 'pending'\n"
        "- Cada sugerencia debe incluir source_chunk_ids y confidence_score\n"
        "- Si no encuentras issues, reporta que el contenido está correcto\n"
        "- Basa tus análisis exclusivamente en el contenido recuperado\n\n"
        "HERRAMIENTAS DISPONIBLES:\n"
        "- search_documents: busca chunks relevantes en ChromaDB\n"
        "- compare_content: compara dos chunks específicos\n"
        "- detect_conflict: busca contradicciones entre documentos\n"
        "- detect_redundancy: detecta información redundante entre chunks\n"
        "- suggest_update: crea una sugerencia para revisión humana\n"
        "- generate_faq_entry: genera una pregunta frecuente\n"
        "- log_action: registra acciones para auditoría"
    )
)

# ── Subgrafo: ReAct Agent ────────────────────────────────────────────────────

if _LLM is not None:
    _react_agent = create_react_agent(
        model=_LLM,
        tools=_TOOLS,
        state_schema=AgentState,
        prompt=_SYSTEM_PROMPT,
        version="v1",
    )
    logger.info("✅ ReAct agent creado con LLM: %s", _LLM.__class__.__name__)
else:
    _react_agent = None
    logger.info("ℹ️  ReAct agent deshabilitado — modo solo pipeline RAG")


async def _safe_react_agent_node(state: AgentState) -> dict:
    """Ejecuta el subgrafo ReAct tolerando fallos del LLM.

    Si el proveedor agota la cuota (429 / ResourceExhausted) o falla por
    cualquier otra razón, el pipeline NO se cae: continúa hacia
    faq_generation (con fallback heurístico) y generate_suggestions
    (hallazgos automáticos), y wait_human_approval restaura el estado
    del documento. Así un fallo del LLM nunca deja documentos
    atascados en 'processing'.
    """
    try:
        return await _react_agent.ainvoke(state)
    except Exception as e:
        logger.warning(
            "⚠️  react_agent falló (%s: %s) — el pipeline continúa sin agente LLM",
            e.__class__.__name__,
            str(e)[:200],
        )
        return {"error": f"react_agent: {e.__class__.__name__}"}


# ── Enrutamiento condicional ─────────────────────────────────────────────────


def _has_documents(state: AgentState) -> str:
    """Decide si cargamos más documentos o terminamos."""
    if state.get("document_ids"):
        return "continue"
    return "end"


# ── Construcción del grafo principal ─────────────────────────────────────────


def _build_graph() -> StateGraph:
    """Construye el grafo principal de curación.

    Flujo completo:
      START → load_documents
        → (sin docs) → END
        → (con docs) → chunk_and_embed → redundancy_detection ─┐
                                        → inconsistency_detection ─┤
                                                                   ↓
                                          react_agent → faq_generation →
                                          generate_suggestions → wait_human_approval → END

    Si no hay LLM configurado, el grafo salta el nodo react_agent:
      chunk_and_embed → redundancy_detection ─┐
                      → inconsistency_detection ─┤
                                                  ↓
                        faq_generation → generate_suggestions → wait_human_approval → END
    """
    builder = StateGraph(AgentState)

    # ── Nodos base ────────────────────────────────────────────────────────
    builder.add_node("load_documents", load_documents_node)
    builder.add_node("chunk_and_embed", chunk_and_embed_node)
    builder.add_node("redundancy_detection", redundancy_detection_node)
    builder.add_node("inconsistency_detection", inconsistency_detection_node)
    builder.add_node("web_search", web_search_node)
    builder.add_node("faq_generation", faq_generation_node)
    builder.add_node("generate_suggestions", generate_suggestions_node)
    builder.add_node("wait_human_approval", wait_human_approval_node)

    # ── Nodo condicional: agente ──────────────────────────────────────────
    # Se envuelve en _safe_react_agent_node para que un fallo del LLM
    # (p. ej. cuota agotada) no tumbe la corrida completa.
    if _react_agent is not None:
        builder.add_node("react_agent", _safe_react_agent_node)

    # ── Aristas ───────────────────────────────────────────────────────────
    builder.set_entry_point("load_documents")

    # load_documents → (sin docs) → END
    #                → (con docs) → chunk_and_embed
    builder.add_conditional_edges(
        "load_documents",
        _has_documents,
        {"continue": "chunk_and_embed", "end": END},
    )

    # chunk_and_embed → redundancy_detection e inconsistency_detection (paralelo)
    builder.add_edge("chunk_and_embed", "redundancy_detection")
    builder.add_edge("chunk_and_embed", "inconsistency_detection")

    # Ambos confluyen en web_search (nodo opcional)
    next_after_detection = "react_agent" if _react_agent else "faq_generation"
    builder.add_edge("redundancy_detection", "web_search")
    builder.add_edge("inconsistency_detection", "web_search")
    builder.add_edge("web_search", next_after_detection)

    if _react_agent is not None:
        builder.add_edge("react_agent", "faq_generation")

    # faq_generation → generate_suggestions → wait_human_approval → END
    builder.add_edge("faq_generation", "generate_suggestions")
    builder.add_edge("generate_suggestions", "wait_human_approval")
    builder.add_edge("wait_human_approval", END)

    return builder


# ── Langfuse handler global (singleton) ───────────────────────────────────────

_langfuse_handler: Optional[Any] = None


def _get_langfuse_handler() -> Optional[Any]:
    """Retorna el handler de Langfuse (singleton)."""
    global _langfuse_handler
    if _langfuse_handler is None:
        _langfuse_handler = _create_langfuse_handler()
    return _langfuse_handler


# ── Checkpointer ────────────────────────────────────────────────────────────

_checkpointer_name = "MemorySaver"
_runtime_graph = None
_runtime_checkpointer = None
_runtime_graph_lock: asyncio.Lock | None = None

# Grafo de inspección/importación.
curation_graph = _build_graph().compile(checkpointer=MemorySaver())
logger.info("✅ Grafo de curación compilado para inspección con MemorySaver")


async def _get_runtime_graph():
    """Retorna el grafo ejecutable con checkpoint persistente en SQLite.

    Usa AsyncSqliteSaver para persistir checkpoints entre corridas.
    Si langgraph-checkpoint-sqlite no está instalado, cae a MemorySaver.
    """
    global _runtime_graph, _runtime_checkpointer, _runtime_graph_lock
    global _checkpointer_name

    if _runtime_graph is not None:
        return _runtime_graph

    if _runtime_graph_lock is None:
        _runtime_graph_lock = asyncio.Lock()

    async with _runtime_graph_lock:
        if _runtime_graph is not None:
            return _runtime_graph

        try:
            import aiosqlite
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

            checkpoint_path = Path(settings.AGENT_CHECKPOINT_DB_PATH)
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            conn = await aiosqlite.connect(str(checkpoint_path))
            _runtime_checkpointer = AsyncSqliteSaver(conn)
            _runtime_graph = _build_graph().compile(checkpointer=_runtime_checkpointer)
            _checkpointer_name = "AsyncSqliteSaver"
            logger.info("✅ AsyncSqliteSaver configurado en %s", checkpoint_path)
        except Exception as exc:
            logger.warning(
                "No se pudo configurar AsyncSqliteSaver (%s); "
                "usando MemorySaver como fallback",
                exc,
            )
            _runtime_checkpointer = MemorySaver()
            _runtime_graph = _build_graph().compile(checkpointer=_runtime_checkpointer)
            _checkpointer_name = "MemorySaver"

        return _runtime_graph


# ── Función helper para invocar el grafo ─────────────────────────────────────


async def run_curation(
    thread_id: Optional[str] = None,
    use_langfuse: bool = True,
    document_ids: Optional[list[str]] = None,
    timeout_seconds: int = 300,
) -> dict:
    """Ejecuta el pipeline completo de curación.

    Args:
        thread_id: Identificador único para esta corrida.
                   Si es None, se genera uno automáticamente.
        use_langfuse: Si incluir tracing con Langfuse (default True).
        document_ids: Lista opcional de IDs de documentos a procesar.
                      Si es None, load_documents_node los busca automáticamente.
        timeout_seconds: Timeout máximo para la ejecución del grafo (default 300s).

    Returns:
        Estado final del grafo después de la ejecución.
    """
    tid = thread_id or f"run-{uuid.uuid4().hex[:12]}"
    logger.info("🚀 Iniciando corrida de curación: thread_id=%s", tid)

    # ── Resumen de configuración de la corrida ────────────────────────────
    if _LLM is None:
        llm_desc = "SIN LLM (modo solo-RAG: redundancia + FAQs heurísticas)"
    else:
        llm_desc = f"{_LLM.__class__.__name__} ({getattr(_LLM, 'model', '?')})"
    has_tavily = bool((settings.TAVILY_API_KEY or "").strip())
    web_chain = (
        "tavily → duckduckgo → wikipedia"
        if settings.WEB_SEARCH_PROVIDER == "tavily" and has_tavily
        else (
            "duckduckgo → tavily → wikipedia"
            if has_tavily
            else "duckduckgo → wikipedia"
        )
    )
    logger.info("  ⚙️  LLM: %s", llm_desc)
    logger.info("  ⚙️  Agente ReAct: %s", "activo" if _react_agent else "deshabilitado")
    logger.info("  ⚙️  Búsqueda web: %s", web_chain)
    logger.info(
        "  ⚙️  Límites: %d docs/corrida | %d docs en paralelo | reintentos LLM: %d",
        settings.MAX_DOCS_PER_CURATION,
        settings.EMBED_CONCURRENCY,
        settings.LLM_MAX_RETRIES,
    )

    if document_ids:
        logger.info("  📋 Documentos específicos: %d proporcionados", len(document_ids))

    config: RunnableConfig = {
        "configurable": {"thread_id": tid},
    }

    # Agregar Langfuse callback si está configurado
    langfuse_handler = _get_langfuse_handler() if use_langfuse else None
    if langfuse_handler is not None:
        config["callbacks"] = [langfuse_handler]
        logger.info("  📊 Tracing con Langfuse activo")

    initial_state: AgentState = {
        "document_ids": document_ids or [],
        "documents_text": {},
        "chunks": [],
        "messages": [
            HumanMessage(
                content=(
                    "Analiza los documentos cargados en el estado, usa las tools disponibles "
                    "cuando necesites evidencia y crea únicamente sugerencias pending con "
                    "source_doc_id, source_chunk_ids y confidence_score."
                )
            )
        ],
        "suggestions": [],
        "redundancy_findings": [],
        "inconsistency_findings": [],
        "terminology_map": {},
        "web_search_results": [],
        "error": None,
    }

    try:
        graph = await _get_runtime_graph()
        result = await asyncio.wait_for(
            graph.ainvoke(initial_state, config),
            timeout=timeout_seconds,
        )
        logger.info("✅ Corrida %s completada exitosamente", tid)
        # Agregar metadata de tracing al resultado
        if langfuse_handler is not None:
            result["_trace_url"] = f"{settings.LANGFUSE_HOST.rstrip('/')}/trace/{tid}"
        return result
    except asyncio.TimeoutError:
        logger.error(
            "❌ Corrida %s excedió el timeout de %ds",
            tid,
            timeout_seconds,
        )
        raise TimeoutError(
            f"La corrida {tid} excedió el timeout de {timeout_seconds}s. "
            f"Considera aumentar 'timeout_seconds' o reducir la cantidad de documentos."
        ) from None
    except Exception as e:
        logger.exception("❌ Error en corrida %s: %s", tid, e)
        raise


# ── Información del grafo ────────────────────────────────────────────────────


def get_graph_info() -> dict:
    """Retorna información del grafo compilado para debugging."""
    if _LLM is None:
        llm_name = "None (solo pipeline RAG)"
    else:
        llm_name = getattr(_LLM, "model_name", _LLM.__class__.__name__)
    langfuse_handler = _get_langfuse_handler()
    return {
        "nodes": list(curation_graph.nodes.keys()),
        "checkpointer": _checkpointer_name,
        "tools": [t.name for t in _TOOLS],
        "llm": str(llm_name),
        "tracing": {
            "langfuse": langfuse_handler is not None,
            "langfuse_configured": bool(settings.LANGFUSE_PUBLIC_KEY.strip()),
        },
    }
