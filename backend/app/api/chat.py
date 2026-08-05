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
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.config import settings
from app.database import get_db
from app.models.models import (
    ChatConversation,
    ChatHistory,
    Document,
    DocumentChunk,
    User,
)
from app.services.access import can_access_doc, visible_docs_filter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

_NO_CONTEXT_ANSWER = (
    "No encontré información suficiente en tu base de conocimiento para "
    "responder esa pregunta. Prueba subiendo documentos relacionados o "
    "reformulando la consulta."
)

# Mensaje distinto cuando el problema no es la pregunta sino que el usuario
# todavía no tiene documentos a su alcance (evita confundir ambas causas).
_NO_DOCUMENTS_ANSWER = (
    "Todavía no hay documentos en tu base de conocimiento. Sube material "
    "del curso desde «Subir documento» y, cuando el agente termine de "
    "analizarlo, podrás hacerle preguntas."
)


# ── Schemas ──────────────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    doc_ids: list[uuid.UUID] | None = None
    # Hilo al que pertenece la pregunta. Si falta, se abre uno nuevo.
    conversation_id: uuid.UUID | None = None


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
    # Documentos dentro del alcance de la búsqueda (transparencia para el
    # usuario: aclara si la respuesta vacía se debe a falta de material)
    searched_documents: int = 0
    # Hilo en el que quedó registrada (el frontend lo necesita cuando la
    # conversación se acaba de crear con esta misma pregunta).
    conversation_id: uuid.UUID | None = None


class ConversationSummary(BaseModel):
    id: uuid.UUID
    title: str
    document_id: uuid.UUID | None = None
    document_name: str | None = None
    message_count: int = 0
    created_at: datetime
    updated_at: datetime


class ConversationsListResponse(BaseModel):
    items: list[ConversationSummary]
    total: int


class CreateConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=160)
    document_id: uuid.UUID | None = None


class RenameConversationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)


class ChatHistoryEntry(BaseModel):
    id: uuid.UUID
    question: str
    answer: str
    has_context: bool
    confidence: float
    sources: list[ChatSource]
    model: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatHistoryResponse(BaseModel):
    items: list[ChatHistoryEntry]
    total: int


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


async def _fallback_chunks_from_postgres(
    db: AsyncSession, doc_id: str, limit: int = 5
) -> list[dict]:
    """Recupera chunks directo de Postgres cuando ChromaDB no devolvió nada.

    Cubre el caso de un documento explícitamente elegido (p. ej. al hacer
    clic en una pregunta sugerida) cuyo contenido SÍ existe (DocumentChunk
    se crea en el mismo pipeline que analiza el documento) pero que por
    algún desajuste con el índice vectorial no aparece en la búsqueda
    semántica. Sin esto, el usuario recibe "no encontré información" sobre
    un documento que evidentemente sí tiene contenido analizado.
    """
    try:
        doc_uuid = uuid.UUID(doc_id)
    except ValueError:
        return []

    rows = (
        await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == doc_uuid)
            .order_by(DocumentChunk.chunk_index)
            .limit(limit)
        )
    ).scalars().all()

    return [
        {
            "chunk_id": c.chroma_id or f"{doc_id}_chunk_{c.chunk_index}",
            "doc_id": doc_id,
            "chunk_index": c.chunk_index,
            "content": c.content,
            # Sin ranking semántico: valor neutro, no comparable al de Chroma.
            "similarity": 0.5,
        }
        for c in rows
    ]


def _title_from_question(question: str) -> str:
    """Título legible a partir de la primera pregunta del hilo."""
    clean = " ".join(question.strip().split())
    return clean[:77] + "…" if len(clean) > 78 else clean


async def _resolve_conversation(
    db: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    question: str,
    document_id: uuid.UUID | None,
) -> ChatConversation | None:
    """Devuelve el hilo indicado, o abre uno nuevo titulado con la pregunta.

    Si el `conversation_id` recibido no existe o es de otro usuario se abre
    uno nuevo en lugar de fallar: perder la respuesta por un id obsoleto
    sería peor que empezar un hilo.
    """
    if conversation_id:
        convo = (
            await db.execute(
                select(ChatConversation).where(
                    ChatConversation.id == conversation_id,
                    ChatConversation.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if convo:
            return convo

    convo = ChatConversation(
        user_id=user_id,
        title=_title_from_question(question),
        document_id=document_id,
    )
    db.add(convo)
    await db.flush()
    return convo


async def _save_history(
    db: AsyncSession,
    user_id: uuid.UUID,
    question: str,
    answer: str,
    *,
    has_context: bool,
    confidence: float,
    sources: list[ChatSource],
    model: str | None,
    searched_documents: int,
    conversation: ChatConversation | None = None,
) -> None:
    """Persiste la pregunta/respuesta para el contador y el panel de historial.

    Un fallo al guardar NO debe romper la respuesta que ya se le va a dar
    al usuario: se registra en el log y se continúa.
    """
    try:
        entry = ChatHistory(
            user_id=user_id,
            conversation_id=conversation.id if conversation else None,
            question=question,
            answer=answer,
            has_context=has_context,
            confidence=confidence,
            sources=[s.model_dump() for s in sources],
            model=model,
            searched_documents=searched_documents,
        )
        db.add(entry)
        if conversation is not None:
            # Ordena la lista de hilos por actividad, no por creación.
            conversation.updated_at = datetime.now(timezone.utc)
        await db.commit()
    except Exception:
        logger.exception("No se pudo guardar el historial del chat")
        await db.rollback()


# ── Endpoint ─────────────────────────────────────────────────────────────────


@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Responde una pregunta usando los documentos accesibles (RAG).

    ALCANCE: el mismo que `GET /api/docs` — material curado privado por
    docente (solo su autor y los administradores), corpus de referencia
    compartido por todos. Se aplica el mismo filtro aquí para que el chat
    nunca diga "no encontré información" sobre un documento que el usuario
    ni siquiera puede ver en la lista, ni tampoco sobre uno que SÍ ve pero
    que pertenece a otro docente.
    """
    # El hilo se resuelve antes de responder para que toda pregunta quede
    # registrada en una conversación, incluidas las que no encuentran contexto.
    conversation = await _resolve_conversation(
        db,
        current_user.id,
        body.conversation_id,
        body.question,
        body.doc_ids[0] if body.doc_ids and len(body.doc_ids) == 1 else None,
    )

    query = select(Document.id, Document.original_filename)
    visibility = visible_docs_filter(current_user)
    if visibility is not None:
        query = query.where(visibility)
    if body.doc_ids:
        query = query.where(Document.id.in_(body.doc_ids))

    rows = (await db.execute(query)).all()
    if not rows:
        logger.info(
            "💬 Chat sin documentos accesibles para %s", current_user.email
        )
        await _save_history(
            db,
            current_user.id,
            body.question,
            _NO_DOCUMENTS_ANSWER,
            has_context=False,
            confidence=0.0,
            sources=[],
            model=None,
            searched_documents=0,
            conversation=conversation,
        )
        return ChatResponse(
            answer=_NO_DOCUMENTS_ANSWER,
            sources=[],
            confidence=0.0,
            has_context=False,
            conversation_id=conversation.id if conversation else None,
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

    # El umbral protege contra falsos positivos al buscar en TODA la base.
    # Si el usuario acotó la consulta a documentos concretos ya declaró el
    # alcance: exigir además alta afinidad haría fallar preguntas legítimas
    # y genéricas ("resume este documento") sobre material corto.
    threshold = 0.0 if body.doc_ids else settings.CHAT_MIN_SIMILARITY
    relevant = [c for c in chunks if c["similarity"] >= threshold]

    # Alcance a UN documento explícito (p. ej. pregunta sugerida) sin
    # resultados en Chroma → intentar con el contenido crudo de Postgres
    # antes de rendirse (ver _fallback_chunks_from_postgres).
    if not relevant and body.doc_ids and len(allowed_ids) == 1:
        relevant = await _fallback_chunks_from_postgres(db, allowed_ids[0])

    if not relevant:
        logger.info("💬 Chat sin contexto relevante para: '%s'", body.question[:60])
        await _save_history(
            db,
            current_user.id,
            body.question,
            _NO_CONTEXT_ANSWER,
            has_context=False,
            confidence=0.0,
            sources=[],
            model=None,
            searched_documents=len(allowed_ids),
            conversation=conversation,
        )
        return ChatResponse(
            answer=_NO_CONTEXT_ANSWER,
            sources=[],
            confidence=0.0,
            has_context=False,
            searched_documents=len(allowed_ids),
            conversation_id=conversation.id if conversation else None,
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
        no_llm_answer = (
            "No hay un modelo de lenguaje configurado, pero encontré estos "
            f"fragmentos relevantes en tus documentos:\n\n{extract}"
        )
        await _save_history(
            db,
            current_user.id,
            body.question,
            no_llm_answer,
            has_context=True,
            confidence=confidence,
            sources=sources,
            model=None,
            searched_documents=len(allowed_ids),
            conversation=conversation,
        )
        return ChatResponse(
            answer=no_llm_answer,
            sources=sources,
            confidence=confidence,
            has_context=True,
            model=None,
            searched_documents=len(allowed_ids),
            conversation_id=conversation.id if conversation else None,
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
    await _save_history(
        db,
        current_user.id,
        body.question,
        answer,
        has_context=True,
        confidence=confidence,
        sources=sources,
        model=str(model_name),
        searched_documents=len(allowed_ids),
        conversation=conversation,
    )
    return ChatResponse(
        answer=answer,
        sources=sources,
        confidence=confidence,
        has_context=True,
        model=str(model_name),
        searched_documents=len(allowed_ids),
        conversation_id=conversation.id if conversation else None,
    )


# ── GET /api/chat/history ────────────────────────────────────────────────────


@router.get("/history", response_model=ChatHistoryResponse)
async def get_chat_history(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    conversation_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Historial personal de preguntas (HU-31).

    Sin `conversation_id` devuelve todas las preguntas del usuario (alimenta el
    contador total); con él, sólo los mensajes de ese hilo, en orden cronológico
    para poder reconstruir la conversación.
    """
    base = select(ChatHistory).where(ChatHistory.user_id == current_user.id)
    count_q = (
        select(func.count())
        .select_from(ChatHistory)
        .where(ChatHistory.user_id == current_user.id)
    )
    if conversation_id:
        base = base.where(ChatHistory.conversation_id == conversation_id)
        count_q = count_q.where(ChatHistory.conversation_id == conversation_id)

    # Dentro de un hilo se lee de la más antigua a la más reciente; el listado
    # general se muestra al revés (lo último preguntado primero).
    order = (
        ChatHistory.created_at.asc() if conversation_id else ChatHistory.created_at.desc()
    )

    total = (await db.execute(count_q)).scalar_one()
    rows = (
        (
            await db.execute(
                base.order_by(order).offset((page - 1) * limit).limit(limit)
            )
        )
        .scalars()
        .all()
    )

    items = [
        ChatHistoryEntry(
            id=r.id,
            question=r.question,
            answer=r.answer,
            has_context=r.has_context,
            confidence=r.confidence,
            sources=[ChatSource(**s) for s in (r.sources or [])],
            model=r.model,
            created_at=r.created_at,
        )
        for r in rows
    ]
    return ChatHistoryResponse(items=items, total=total)


# ── Conversaciones ───────────────────────────────────────────────────────────


async def _owned_conversation(
    db: AsyncSession, conversation_id: uuid.UUID, user: User
) -> ChatConversation:
    """Recupera un hilo del usuario o lanza 404.

    Devuelve 404 —y no 403— cuando el hilo es de otra persona: confirmar su
    existencia filtraría información sobre conversaciones ajenas.
    """
    convo = (
        await db.execute(
            select(ChatConversation).where(
                ChatConversation.id == conversation_id,
                ChatConversation.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if not convo:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    return convo


@router.get("/conversations", response_model=ConversationsListResponse)
async def list_conversations(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Hilos del usuario, del más activo al más antiguo."""
    total = (
        await db.execute(
            select(func.count())
            .select_from(ChatConversation)
            .where(ChatConversation.user_id == current_user.id)
        )
    ).scalar_one()

    # Conteo de mensajes y nombre del documento en una sola consulta.
    rows = (
        await db.execute(
            select(
                ChatConversation,
                Document.filename,
                func.count(ChatHistory.id),
            )
            .outerjoin(Document, Document.id == ChatConversation.document_id)
            .outerjoin(
                ChatHistory, ChatHistory.conversation_id == ChatConversation.id
            )
            .where(ChatConversation.user_id == current_user.id)
            .group_by(ChatConversation.id, Document.filename)
            .order_by(ChatConversation.updated_at.desc())
            .limit(limit)
        )
    ).all()

    items = [
        ConversationSummary(
            id=convo.id,
            title=convo.title,
            document_id=convo.document_id,
            document_name=doc_name,
            message_count=count or 0,
            created_at=convo.created_at,
            updated_at=convo.updated_at,
        )
        for convo, doc_name, count in rows
    ]
    return ConversationsListResponse(items=items, total=total)


@router.post(
    "/conversations",
    response_model=ConversationSummary,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    body: CreateConversationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Abre un hilo vacío, opcionalmente acotado a un documento."""
    doc_name = None
    if body.document_id:
        doc = (
            await db.execute(
                select(Document).where(Document.id == body.document_id)
            )
        ).scalar_one_or_none()
        if not doc or not can_access_doc(doc, current_user):
            raise HTTPException(
                status_code=404, detail="Documento no encontrado"
            )
        doc_name = doc.filename

    convo = ChatConversation(
        user_id=current_user.id,
        title=(body.title or "").strip() or "Nueva conversación",
        document_id=body.document_id,
    )
    db.add(convo)
    await db.commit()
    await db.refresh(convo)

    return ConversationSummary(
        id=convo.id,
        title=convo.title,
        document_id=convo.document_id,
        document_name=doc_name,
        message_count=0,
        created_at=convo.created_at,
        updated_at=convo.updated_at,
    )


@router.patch("/conversations/{conversation_id}", response_model=ConversationSummary)
async def rename_conversation(
    conversation_id: uuid.UUID,
    body: RenameConversationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    convo = await _owned_conversation(db, conversation_id, current_user)
    convo.title = body.title.strip()
    await db.commit()
    await db.refresh(convo)

    doc_name = None
    if convo.document_id:
        doc_name = (
            await db.execute(
                select(Document.filename).where(Document.id == convo.document_id)
            )
        ).scalar_one_or_none()
    count = (
        await db.execute(
            select(func.count())
            .select_from(ChatHistory)
            .where(ChatHistory.conversation_id == convo.id)
        )
    ).scalar_one()

    return ConversationSummary(
        id=convo.id,
        title=convo.title,
        document_id=convo.document_id,
        document_name=doc_name,
        message_count=count or 0,
        created_at=convo.created_at,
        updated_at=convo.updated_at,
    )


@router.delete(
    "/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_conversation(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Elimina el hilo y sus mensajes (ON DELETE CASCADE)."""
    convo = await _owned_conversation(db, conversation_id, current_user)
    await db.delete(convo)
    await db.commit()
