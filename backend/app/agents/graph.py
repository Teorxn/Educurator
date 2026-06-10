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
import os
from pathlib import Path
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import create_react_agent

from app.agents.nodes import (
    chunk_and_embed_node,
    generate_suggestions_node,
    load_documents_node,
    redundancy_detection_node,
    wait_human_approval_node,
)
from app.agents.state import AgentState
from app.config import settings
from app.tools.registry import get_all_tools

logger = logging.getLogger(__name__)


# ── Factory: crear el LLM según configuración ────────────────────────────────


def _create_llm():
    """Crea el modelo de lenguaje según la configuración disponible.

    Orden de preferencia:
      1. OpenAI        (si OPENAI_API_KEY está configurada y no es placeholder)
      2. Google Gemini  (si GEMINI_API_KEY está configurada)
      3. Hugging Face  (si HUGGINGFACE_MODEL está configurado)
      4. None          (modo solo pipeline RAG, sin agente)
    """
    openai_key = os.getenv("OPENAI_API_KEY", "")
    has_openai = bool(openai_key) and openai_key != "sk-..."

    if has_openai:
        from langchain_openai import ChatOpenAI

        logger.info("Usando OpenAI: gpt-4o-mini")
        return ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0,
        )

    gemini_key = getattr(settings, "GEMINI_API_KEY", None) or os.getenv(
        "GEMINI_API_KEY", ""
    )
    if gemini_key:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI

            logger.info("Usando Google Gemini: gemini-2.5-flash")
            return ChatGoogleGenerativeAI(
                model="gemini-2.5-flash",
                temperature=0,
                api_key=gemini_key,
            )
        except Exception as e:
            logger.warning("Error configurando Gemini: %s", e)

    hf_model = getattr(settings, "HUGGINGFACE_MODEL", None) or os.getenv(
        "HUGGINGFACE_MODEL", ""
    )
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
        state_modifier=_SYSTEM_PROMPT,
    )
    logger.info("✅ ReAct agent creado con LLM: %s", _LLM.__class__.__name__)
else:
    _react_agent = None
    logger.info("ℹ️  ReAct agent deshabilitado — modo solo pipeline RAG")


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
        → (con docs) → chunk_and_embed → react_agent →
          generate_suggestions → wait_human_approval → END

    Si no hay LLM configurado, el grafo salta el nodo react_agent
    y va directamente de chunk_and_embed a generate_suggestions.
    """
    builder = StateGraph(AgentState)

    # ── Nodos base ────────────────────────────────────────────────────────
    builder.add_node("load_documents", load_documents_node)
    builder.add_node("chunk_and_embed", chunk_and_embed_node)
    builder.add_node("redundancy_detection", redundancy_detection_node)
    builder.add_node("generate_suggestions", generate_suggestions_node)
    builder.add_node("wait_human_approval", wait_human_approval_node)

    # ── Nodo condicional: agente ──────────────────────────────────────────
    if _react_agent is not None:
        builder.add_node("react_agent", _react_agent)

    # ── Aristas ───────────────────────────────────────────────────────────
    builder.set_entry_point("load_documents")

    # load_documents → (sin docs) → END
    #                → (con docs) → chunk_and_embed
    builder.add_conditional_edges(
        "load_documents",
        _has_documents,
        {"continue": "chunk_and_embed", "end": END},
    )

    # chunk_and_embed → redundancy_detection → react_agent (si existe)
    #                                      → generate_suggestions (directo)
    builder.add_edge("chunk_and_embed", "redundancy_detection")

    next_after_red = "react_agent" if _react_agent else "generate_suggestions"
    builder.add_edge("redundancy_detection", next_after_red)

    if _react_agent is not None:
        builder.add_edge("react_agent", "generate_suggestions")

    builder.add_edge("generate_suggestions", "wait_human_approval")
    builder.add_edge("wait_human_approval", END)

    return builder


# ── Checkpointer: AsyncSqliteSaver ───────────────────────────────────────────

_checkpointer_name = "AsyncSqliteSaver"
_runtime_graph = None
_runtime_checkpointer = None
_runtime_checkpoint_conn = None
_runtime_graph_lock: asyncio.Lock | None = None

# Grafo de inspección/importación. La ejecución real usa _get_runtime_graph(),
# porque AsyncSqliteSaver debe construirse dentro de un event loop activo.
curation_graph = _build_graph().compile(checkpointer=MemorySaver())
logger.info("✅ Grafo de curación compilado para inspección con MemorySaver")


async def _get_runtime_graph():
    """Retorna el grafo ejecutable con checkpoint persistente en SQLite.

    LangGraph requiere AsyncSqliteSaver para usar ainvoke/astream. Como ese saver
    necesita un event loop activo, se inicializa de forma lazy en la primera corrida.
    """
    global _runtime_graph, _runtime_checkpointer, _runtime_checkpoint_conn
    global _runtime_graph_lock, _checkpointer_name

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
            _runtime_checkpoint_conn = conn
            _runtime_checkpointer = AsyncSqliteSaver(conn)
            _runtime_graph = _build_graph().compile(checkpointer=_runtime_checkpointer)
            _checkpointer_name = "AsyncSqliteSaver"
            logger.info("✅ AsyncSqliteSaver configurado en %s", checkpoint_path)
        except ImportError as exc:
            logger.warning(
                "langgraph-checkpoint-sqlite/aiosqlite no está instalado; "
                "usando MemorySaver: %s",
                exc,
            )
            _runtime_checkpointer = MemorySaver()
            _runtime_graph = _build_graph().compile(checkpointer=_runtime_checkpointer)
            _checkpointer_name = "MemorySaver"

        return _runtime_graph


# ── Función helper para invocar el grafo ─────────────────────────────────────


async def run_curation(
    thread_id: Optional[str] = None,
) -> dict:
    """Ejecuta el pipeline completo de curación.

    Args:
        thread_id: Identificador único para esta corrida.
                   Si es None, se genera uno automáticamente.

    Returns:
        Estado final del grafo después de la ejecución.
    """
    import uuid

    tid = thread_id or f"run-{uuid.uuid4().hex[:12]}"
    logger.info("🚀 Iniciando corrida de curación: thread_id=%s", tid)

    config: RunnableConfig = {"configurable": {"thread_id": tid}}

    initial_state: AgentState = {
        "document_ids": [],
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
        "error": None,
    }

    try:
        graph = await _get_runtime_graph()
        result = await graph.ainvoke(initial_state, config)
        logger.info("✅ Corrida %s completada exitosamente", tid)
        return result
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
    return {
        "nodes": list(curation_graph.nodes.keys()),
        "checkpointer": _checkpointer_name,
        "tools": [t.name for t in _TOOLS],
        "llm": str(llm_name),
    }
