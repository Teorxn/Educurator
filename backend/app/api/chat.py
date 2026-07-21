"""
HU-31 — Consultar información mediante lenguaje natural.

POST /api/chat: pregunta en lenguaje natural → respuesta fundamentada
ÚNICAMENTE en los documentos del usuario recuperados por RAG, con las
fuentes citadas (documento + chunk + extracto) y un indicador de
confianza derivado de la similitud semántica.

Reglas anti-alucinación:
  - El contexto se limita a los chunks recuperados de ChromaDB.
  - Si ningún chunk supera el umbral de similitud, se responde
    explícitamente que no hay información suficiente (sin llamar al LLM).
  - El prompt prohíbe usar conocimiento general del modelo.
"""

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.config import settings
from app.database import get_db
from app.models.models import Document, User, UserRole

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

_NO_CONTEXT_ANSWER = (
    "No encontré información suficiente en tu base de conocimiento para "
    "responder esa pregunta. Prueba subiendo documentos relacionados o "
    "reformulando la consulta."
)


# ── Schemas ──────────────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    doc_ids: list[uuid.UUID] | None = None


class ChatSource(BaseModel):
    doc_id: str
    doc_name: str
    chunk_index: int
    excerpt: str
    similarity: float


class ChatResponse(BaseModel):
    answer: str
    sources: list[ChatSource]
    confidence: float
    has_context: bool
    model: str | None = None


# ── Recuperación (RAG) ───────────────────────────────────────────────────────


def _retrieve_chunks(question: str, allowed_doc_ids: list[str], top_k: int) -> list[dict]:
    """Busca en ChromaDB los chunks más relevantes entre los documentos permitidos.

    Bloqueante (ChromaDB + sentence-transformers) → se ejecuta en un thread.
    """
    from app.rag.embeddings import get_chroma_collection, get_embedding_model

    if not allowed_doc_ids:
        return []

    model = get_embedding_model()
    query_emb = model.encode(question).tolist()
    collection = get_chroma_collection()

    where = (
        {"doc_id": allowed_doc_ids[0]}
        if len(allowed_doc_ids) == 1
        else {"doc_id": {"$in": allowed_doc_ids}}
    )
    res = collection.query(
        query_embeddings=[query_emb],
        n_results=max(1, top_k),
        where=where,
        include=["documents", "metadatas", "embeddings"],
    )
    if not res.get("ids") or not res["ids"][0]:
        return []

    # Similitud coseno real: las 'distances' de Chroma son L2 y no sirven
    from app.rag.redundancy import _cosine_similarity

    embs = res.get("embeddings")
    out: list[dict] = []
    for i, chunk_id in enumerate(res["ids"][0]):
        meta = res["metadatas"][0][i] if res.get("metadatas") else {}
        content = res["documents"][0][i] if res.get("documents") else ""
        similarity = 0.0
        try:
            if embs is not None and len(embs[0]) > i and embs[0][i] is not None:
                similarity = float(_cosine_similarity(query_emb, embs[0][i]))
        except Exception:
            similarity = 0.0
        out.append(
            {
                "chunk_id": chunk_id,
                "doc_id": (meta or {}).get("doc_id", ""),
                "chunk_index": int((meta or {}).get("chunk_index", 0)),
                "content": content or "",
                "similarity": round(similarity, 4),
            }
        )

    out.sort(key=lambda c: c["similarity"], reverse=True)
    return out


# ── Endpoint ─────────────────────────────────────────────────────────────────


@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Responde una pregunta usando solo los documentos del usuario (RAG)."""
    # ── 1. Alcance: documentos del usuario (admin ve todos) ───────────────
    query = select(Document.id, Document.original_filename)
    if current_user.role != UserRole.admin:
        query = query.where(Document.uploaded_by == current_user.id)
    if body.doc_ids:
        query = query.where(Document.id.in_(body.doc_ids))

    rows = (await db.execute(query)).all()
    if not rows:
        return ChatResponse(
            answer=_NO_CONTEXT_ANSWER, sources=[], confidence=0.0, has_context=False
        )

    doc_names = {str(doc_id): name for doc_id, name in rows}
    allowed_ids = list(doc_names.keys())

    # ── 2. Recuperación semántica ─────────────────────────────────────────
    try:
        chunks = await asyncio.to_thread(
            _retrieve_chunks, body.question, allowed_ids, settings.CHAT_TOP_K
        )
    except Exception as e:
        logger.exception("Error recuperando contexto para el chat")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No se pudo consultar la base de conocimiento: {e}",
        )

    relevant = [c for c in chunks if c["similarity"] >= settings.CHAT_MIN_SIMILARITY]
    if not relevant:
        logger.info("💬 Chat sin contexto relevante para: '%s'", body.question[:60])
        return ChatResponse(
            answer=_NO_CONTEXT_ANSWER, sources=[], confidence=0.0, has_context=False
        )

    sources = [
        ChatSource(
            doc_id=c["doc_id"],
            doc_name=doc_names.get(c["doc_id"], "documento"),
            chunk_index=c["chunk_index"],
            excerpt=c["content"][:300],
            similarity=c["similarity"],
        )
        for c in relevant
    ]
    confidence = round(sum(c["similarity"] for c in relevant) / len(relevant), 4)

    # ── 3. Generación fundamentada ────────────────────────────────────────
    from app.agents.graph import get_llm

    llm = get_llm()
    if llm is None:
        # Sin LLM: devolver los extractos recuperados (sigue siendo útil y honesto)
        extract = "\n\n".join(
            f"• {s.doc_name} (fragmento {s.chunk_index}): {s.excerpt}"
            for s in sources[:3]
        )
        return ChatResponse(
            answer=(
                "No hay un modelo de lenguaje configurado, pero encontré estos "
                f"fragmentos relevantes en tus documentos:\n\n{extract}"
            ),
            sources=sources,
            confidence=confidence,
            has_context=True,
            model=None,
        )

    from langchain_core.messages import HumanMessage, SystemMessage

    context_block = "\n\n".join(
        f"[FUENTE {i + 1}] Documento: {s.doc_name} (fragmento {s.chunk_index})\n"
        f"{c['content'][:1500]}"
        for i, (s, c) in enumerate(zip(sources, relevant))
    )
    system_prompt = SystemMessage(
        content=(
            "Eres un asistente que responde preguntas sobre el material de un "
            "curso universitario.\n\n"
            "REGLAS ESTRICTAS:\n"
            "- Responde ÚNICAMENTE con información presente en las FUENTES "
            "proporcionadas. Está prohibido usar conocimiento general.\n"
            "- Si las fuentes no contienen la respuesta, dilo explícitamente.\n"
            "- Cita las fuentes que usaste indicando el documento.\n"
            "- Responde en español, de forma clara y concisa (máx. 5 oraciones)."
        )
    )
    human_prompt = HumanMessage(
        content=f"FUENTES:\n{context_block}\n\nPREGUNTA: {body.question}"
    )

    model_name = getattr(llm, "model", None) or llm.__class__.__name__
    try:
        from app.tools.registry import _ainvoke_llm_with_retry

        response = await _ainvoke_llm_with_retry(llm, [system_prompt, human_prompt])
        content = response.content
        if not isinstance(content, str):
            parts = []
            for item in content or []:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(item.get("text", ""))
            content = " ".join(parts)
        answer = (content or "").strip() or _NO_CONTEXT_ANSWER

        # HU-32: registrar consumo de tokens de esta consulta
        from app.services.tokens import track_llm_call

        await track_llm_call(
            response,
            operation="chat",
            model=str(model_name),
            prompt_text=f"{system_prompt.content}\n{human_prompt.content}",
            user_id=str(current_user.id),
        )
    except Exception as e:
        logger.warning("El LLM falló respondiendo el chat: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El modelo de lenguaje no está disponible en este momento. "
            "Intenta de nuevo en unos segundos.",
        )

    logger.info(
        "💬 Chat respondido (%d fuentes, confianza %.2f): '%s'",
        len(sources),
        confidence,
        body.question[:60],
    )
    return ChatResponse(
        answer=answer,
        sources=sources,
        confidence=confidence,
        has_context=True,
        model=str(model_name),
    )
