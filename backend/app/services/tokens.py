"""
HU-32 — Consultar el consumo de tokens.

Registra el consumo de cada llamada al LLM y calcula el costo estimado
según las tarifas configuradas en .env. Si el proveedor reporta el uso
real (usage_metadata de LangChain) se usa ese dato; si no, se estima
con tiktoken sobre el texto de entrada/salida.
"""

import logging
import uuid
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger(__name__)


def _count_tokens(text: str) -> int:
    """Estima tokens con tiktoken (fallback: ~4 caracteres por token)."""
    if not text:
        return 0
    try:
        import tiktoken

        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except Exception:
        return max(1, len(text) // 4)


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    """Costo estimado en USD según las tarifas configuradas por 1k tokens."""
    cost_in = (input_tokens / 1000) * settings.LLM_COST_PER_1K_INPUT_TOKENS
    cost_out = (output_tokens / 1000) * settings.LLM_COST_PER_1K_OUTPUT_TOKENS
    return round(cost_in + cost_out, 6)


def extract_usage(response: Any, prompt_text: str = "") -> tuple[int, int]:
    """Obtiene (input_tokens, output_tokens) de una respuesta del LLM.

    Prioriza el uso real reportado por el proveedor; si no viene, estima
    con tiktoken.
    """
    usage = getattr(response, "usage_metadata", None) or {}
    if isinstance(usage, dict) and usage:
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        if input_tokens or output_tokens:
            return input_tokens, output_tokens

    # Fallback: estimar con tiktoken
    content = getattr(response, "content", "") or ""
    if not isinstance(content, str):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get("text", ""))
        content = " ".join(parts)
    return _count_tokens(prompt_text), _count_tokens(content)


async def record_usage(
    *,
    operation: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    thread_id: Optional[str] = None,
    document_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """Persiste el consumo de una llamada al LLM (best-effort).

    Nunca interrumpe el pipeline: si falla el registro, solo se avisa.
    """
    if input_tokens <= 0 and output_tokens <= 0:
        return

    try:
        from app.database import AsyncSessionLocal
        from app.models.models import TokenUsage

        total = input_tokens + output_tokens
        cost = estimate_cost(input_tokens, output_tokens)

        async with AsyncSessionLocal() as db:
            db.add(
                TokenUsage(
                    operation=operation,
                    model=model or "unknown",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total,
                    cost_usd=cost,
                    thread_id=thread_id,
                    document_id=uuid.UUID(document_id) if document_id else None,
                    user_id=uuid.UUID(user_id) if user_id else None,
                )
            )
            await db.commit()

        logger.info(
            "  💰 Tokens [%s/%s]: %d in + %d out = %d (~$%.5f)",
            operation,
            model,
            input_tokens,
            output_tokens,
            total,
            cost,
        )
    except Exception as e:
        logger.warning("No se pudo registrar el consumo de tokens: %s", e)


async def track_llm_call(
    response: Any,
    *,
    operation: str,
    model: str,
    prompt_text: str = "",
    thread_id: Optional[str] = None,
    document_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """Atajo: extrae el uso de una respuesta del LLM y lo persiste."""
    input_tokens, output_tokens = extract_usage(response, prompt_text)
    await record_usage(
        operation=operation,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        thread_id=thread_id,
        document_id=document_id,
        user_id=user_id,
    )
