"""
HU-16 — Mejorar recomendaciones futuras.

Construye un contexto de retroalimentación a partir de los últimos
feedback_patterns del instructor (aprobaciones y, sobre todo, rechazos
con motivo). Ese contexto se inyecta en el mensaje inicial del agente
ReAct para que ajuste sus sugerencias a las preferencias observadas.

La cantidad de patrones se controla con FEEDBACK_CONTEXT_SIZE (env).
"""

import logging

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.models import FeedbackPattern, Suggestion

logger = logging.getLogger(__name__)


async def get_feedback_context(limit: int | None = None) -> str:
    """Retorna un bloque de texto con los últimos patrones de feedback.

    Prioriza el feedback más reciente. Cada línea incluye el veredicto
    (aprobada/rechazada), el tipo de sugerencia y el comentario del
    instructor si existe.

    Returns:
        Bloque de texto listo para inyectar en el prompt, o cadena vacía
        si no hay feedback registrado (el agente funciona igual sin él).
    """
    n = limit if limit is not None else getattr(settings, "FEEDBACK_CONTEXT_SIZE", 5)
    if n <= 0:
        return ""

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(FeedbackPattern, Suggestion)
                .join(Suggestion, FeedbackPattern.suggestion_id == Suggestion.id)
                .order_by(FeedbackPattern.created_at.desc())
                .limit(n)
            )
            rows = result.all()
    except Exception as e:
        logger.warning("No se pudo cargar feedback_patterns: %s", e)
        return ""

    if not rows:
        logger.info("  🧠 Sin feedback previo del instructor — prompt sin ajustes")
        return ""

    lines: list[str] = []
    for fb, sug in rows:
        verdict = "APROBADA" if fb.feedback_type == "approve" else "RECHAZADA"
        s_type = sug.type.value if hasattr(sug.type, "value") else str(sug.type)
        desc = (sug.description or "")[:120]
        line = f"- [{verdict}] tipo={s_type}: \"{desc}\""
        if fb.comment:
            line += f' | Motivo del instructor: "{fb.comment[:200]}"'
        lines.append(line)

    n_rejects = sum(1 for fb, _ in rows if fb.feedback_type == "reject")
    logger.info(
        "  🧠 Inyectando %d patrones de feedback al agente (%d rechazos con contexto)",
        len(lines),
        n_rejects,
    )

    return (
        "\n\nRETROALIMENTACIÓN PREVIA DEL INSTRUCTOR (aprende de estos patrones):\n"
        + "\n".join(lines)
        + "\n\nAjusta tus sugerencias: evita repetir los patrones RECHAZADOS "
        "y prioriza el estilo de las sugerencias APROBADAS."
    )
