"""
HU-06 — Analizar documentos automáticamente.

Endpoints para disparar y monitorear el pipeline de curación
orquestado por LangGraph con trazabilidad vía Langfuse.
"""

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.api.dependencies import get_current_user, require_role
from app.models.models import User, UserRole

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

# ── Almacén en memoria para seguimiento de corridas ──────────────────────────
# En producción, esto debería ir a una BD. Para MVP es suficiente.
_runs: dict[str, dict] = {}


# ── POST /api/analysis/detect-redundancy ────────────────────────────────────────


@router.post(
    "/detect-redundancy",
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_redundancy_scan(
    background_tasks: BackgroundTasks,
    include_same_doc: bool = False,
    max_pairs: int = 50,
    current_user: User = Depends(require_role(UserRole.instructor, UserRole.admin)),
):
    """Escanea toda la colección en busca de información redundante.

    A diferencia del pipeline completo de curación, este endpoint SOLO ejecuta
    la detección de redundancia sobre todos los documentos existentes,
    sin pasar por el agente ReAct ni generar otros tipos de sugerencias.

    Args:
        include_same_doc: Si incluir redundancia intra-documento.
        max_pairs: Máximo de pares redundantes a retornar.

    Returns:
        thread_id para consultar el estado del escaneo.
    """
    tid = f"redundancy-scan-{uuid.uuid4().hex[:12]}"

    _runs[tid] = {
        "thread_id": tid,
        "status": "running",
        "triggered_by": str(current_user.id),
        "error": None,
        "result": None,
        "type": "redundancy_scan",
    }

    background_tasks.add_task(
        _execute_redundancy_scan, tid, include_same_doc, max_pairs
    )

    logger.info(
        "🚀 Escaneo de redundancia disparado por usuario %s: thread_id=%s",
        current_user.id,
        tid,
    )

    return {
        "status": "accepted",
        "thread_id": tid,
        "message": "Escaneo de redundancia iniciado. Usa GET /api/analysis/status/{thread_id} para monitorear.",
    }


async def _execute_redundancy_scan(
    tid: str,
    include_same_doc: bool = False,
    max_pairs: int = 50,
) -> None:
    """Ejecuta el escaneo de redundancia y actualiza el estado."""
    from app.rag.redundancy import scan_all_redundancy

    try:
        pairs = await scan_all_redundancy(
            include_same_doc=include_same_doc,
            max_pairs=max_pairs,
        )
        _runs[tid]["status"] = "completed"
        _runs[tid]["result"] = {
            "total_pairs": len(pairs),
            "pairs": [
                {
                    "chunk_id_a": p.chunk_id_a,
                    "chunk_id_b": p.chunk_id_b,
                    "similarity": p.similarity,
                    "confidence_score": p.confidence_score,
                    "doc_id_a": p.doc_id_a,
                    "doc_id_b": p.doc_id_b,
                    "content_a_preview": p.content_a_preview,
                    "content_b_preview": p.content_b_preview,
                }
                for p in pairs
            ],
        }
        logger.info(
            "✅ Escaneo de redundancia %s completado: %d pares", tid, len(pairs)
        )
    except Exception as e:
        logger.exception("❌ Error en escaneo de redundancia %s: %s", tid, e)
        _runs[tid]["status"] = "failed"
        _runs[tid]["error"] = str(e)


# ── POST /api/analysis/curate ─────────────────────────────────────────────────


@router.post(
    "/curate",
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_curation(
    background_tasks: BackgroundTasks,
    thread_id: Optional[str] = None,
    current_user: User = Depends(require_role(UserRole.instructor, UserRole.admin)),
):
    """Dispara el pipeline completo de curación en segundo plano.

    Ejecuta los nodos del grafo LangGraph:
      load_documents → chunk_and_embed → redundancy_detection →
      react_agent → generate_suggestions → wait_human_approval

    Returns:
        thread_id para consultar el estado de la corrida.
    """
    tid = thread_id or f"curation-{uuid.uuid4().hex[:12]}"

    # Registrar corrida
    _runs[tid] = {
        "thread_id": tid,
        "status": "running",
        "triggered_by": str(current_user.id),
        "error": None,
        "result": None,
    }

    # Ejecutar en background
    background_tasks.add_task(_execute_curation, tid, str(current_user.id))

    logger.info(
        "🚀 Análisis disparado por usuario %s: thread_id=%s",
        current_user.id,
        tid,
    )

    return {
        "status": "accepted",
        "thread_id": tid,
        "message": "Análisis iniciado. Usa GET /api/analysis/status/{thread_id} para monitorear.",
    }


async def _execute_curation(tid: str, triggered_by: Optional[str] = None) -> None:
    """Ejecuta el pipeline y actualiza el estado de la corrida."""
    from app.agents.graph import run_curation

    try:
        result = await run_curation(thread_id=tid, triggered_by=triggered_by)
        _runs[tid]["status"] = "completed"
        _runs[tid]["result"] = _summarize_result(result)
        trace_url = result.get("_trace_url")
        if trace_url:
            _runs[tid]["trace_url"] = trace_url
        logger.info("✅ Corrida %s completada exitosamente", tid)
    except Exception as e:
        logger.exception("❌ Error en corrida %s: %s", tid, e)
        _runs[tid]["status"] = "failed"
        _runs[tid]["error"] = str(e)


def _summarize_result(result: dict) -> dict:
    """Resume el resultado del grafo para la respuesta API.

    Incluye documentos procesados, sugerencias generadas (por tipo),
    pares redundantes encontrados, y metadatos del agente.
    """
    suggestions = result.get("suggestions", [])
    redundancy_findings = result.get("redundancy_findings", [])
    doc_ids = result.get("document_ids", [])
    error = result.get("error")

    # Contar sugerencias por tipo
    suggestions_by_type: dict[str, int] = {}
    for s in suggestions:
        stype = s.get("type", "unknown")
        suggestions_by_type[stype] = suggestions_by_type.get(stype, 0) + 1

    return {
        "documents_processed": len(doc_ids),
        "document_ids": doc_ids,
        "suggestions_generated": len(suggestions),
        "suggestions_by_type": suggestions_by_type,
        "redundancy_pairs_found": len(redundancy_findings),
        "error": error,
        "suggestions": [
            {
                "id": s.get("id"),
                "document_id": s.get("document_id"),
                "type": s.get("type"),
                "confidence_score": s.get("confidence_score"),
            }
            for s in suggestions
        ],
    }


# ── GET /api/analysis/info ─────────────────────────────────────────────────────


@router.get("/info")
async def get_analysis_info(
    current_user: User = Depends(get_current_user),
):
    """Retorna información del grafo de curación para monitoreo.

    Útil para que el frontend sepa qué capacidades están disponibles
    (LLM configurado, tools registradas, tracing activo).
    """
    from app.agents.graph import get_graph_info

    return get_graph_info()


# ── GET /api/analysis/graph ───────────────────────────────────────────────────


@router.get("/graph")
async def get_graph_diagram(
    current_user: User = Depends(get_current_user),
):
    """Retorna el diagrama del grafo LangGraph en formato Mermaid.

    El diagrama se genera desde el grafo COMPILADO (no está dibujado a
    mano): refleja siempre los nodos y aristas reales, incluyendo las
    ramas condicionales. El frontend lo renderiza con mermaid.js.
    """
    from app.agents.graph import curation_graph, get_graph_info

    try:
        mermaid = curation_graph.get_graph().draw_mermaid()
    except Exception as e:
        logger.error("Error generando diagrama Mermaid: %s", e)
        raise HTTPException(
            status_code=500, detail=f"No se pudo generar el diagrama: {e}"
        )

    info = get_graph_info()
    return {
        "mermaid": mermaid,
        "nodes": info["nodes"],
        "llm": info["llm"],
    }


# ── GET /api/analysis/status/{thread_id} ──────────────────────────────────────


@router.get("/status/{thread_id}")
async def get_curation_status(
    thread_id: str,
    current_user: User = Depends(get_current_user),
):
    """Consulta el estado de una corrida de análisis."""
    run_data = _runs.get(thread_id)
    if not run_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró la corrida '{thread_id}'. "
            f"Las corridas completadas se limpian al reiniciar el servidor.",
        )

    return run_data


# ── GET /api/analysis/runs ────────────────────────────────────────────────────


@router.get("/runs")
async def list_curation_runs(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
):
    """HU-19 — Lista el histórico de corridas del agente (persistente).

    Lee de la tabla agent_runs, que sobrevive reinicios del servidor.
    Incluye fecha, estado, duración, documentos procesados, sugerencias
    generadas y resumen por tipo.
    """
    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.models.models import AgentRun

    limit = max(1, min(limit, 200))

    rows: list[AgentRun] = []
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(AgentRun).order_by(AgentRun.started_at.desc()).limit(limit)
            )
            rows = list(result.scalars().all())
    except Exception as e:
        logger.warning("No se pudo leer agent_runs de la DB: %s", e)

    runs = [
        {
            "thread_id": r.thread_id,
            "status": r.status.value if hasattr(r.status, "value") else r.status,
            "triggered_by": str(r.triggered_by) if r.triggered_by else None,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "duration_seconds": r.duration_seconds,
            "documents_processed": r.documents_processed,
            "suggestions_generated": r.suggestions_generated,
            "summary": r.summary,
            "error": r.error,
            "trace_url": r.trace_url,
        }
        for r in rows
    ]

    # Corridas recién disparadas que aún no llegaron a la DB
    # (la fila se crea dentro de run_curation, en el background task)
    db_tids = {r["thread_id"] for r in runs}
    pending_memory = [
        {
            "thread_id": tid,
            "status": data.get("status"),
            "triggered_by": data.get("triggered_by"),
            "started_at": None,
            "finished_at": None,
            "duration_seconds": None,
            "documents_processed": 0,
            "suggestions_generated": 0,
            "summary": None,
            "error": data.get("error"),
            "trace_url": data.get("trace_url"),
        }
        for tid, data in _runs.items()
        if tid not in db_tids
    ]

    all_runs = pending_memory + runs
    return {"total": len(all_runs), "runs": all_runs}
