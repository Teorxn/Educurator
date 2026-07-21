"""
#26 — Test de integración del flujo completo:
    upload → pipeline del agente → sugerencia → aprobación humana.

Usa la API real (FastAPI vía ASGITransport) y la base de datos real de
desarrollo. Solo se mockean los servicios EXTERNOS (ChromaDB, LLM,
búsqueda web) para que el test sea determinista y no consuma cuota.

Se salta automáticamente si Postgres no está disponible.
Limpia todos los registros que crea (documento, chunks, sugerencias,
feedback, historial y archivo subido).
"""

import json
import uuid as uuid_mod
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, text

from app.api.dependencies import get_current_user
from app.database import AsyncSessionLocal
from app.main import app
from app.models.models import (
    Document,
    DocumentChunk,
    DocumentHistory,
    FeedbackPattern,
    Suggestion,
    SuggestionStatus,
    User,
    UserRole,
)

pytestmark = pytest.mark.asyncio

_DOC_TEXT = (
    "El curso de Cálculo Diferencial tiene una duración total de 64 horas. "
    "Las clases se imparten los lunes y miércoles en el aula 301. "
    "La evaluación consiste en tres parciales y un examen final acumulativo. "
    "Los estudiantes deben asistir al menos al 80 por ciento de las sesiones."
)


async def _db_available() -> bool:
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def _get_or_create_user() -> tuple[User, bool]:
    """Retorna un usuario instructor real (lo crea si no hay ninguno)."""
    async with AsyncSessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.is_active).limit(1))
        ).scalar_one_or_none()
        if user:
            return user, False

        user = User(
            email=f"integ-{uuid_mod.uuid4().hex[:8]}@test.dev",
            hashed_password="not-a-real-hash",
            role=UserRole.instructor,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user, True


async def _cleanup(doc_id: str | None, created_user_id=None) -> None:
    """Borra en orden inverso de dependencias todo lo creado por el test."""
    async with AsyncSessionLocal() as db:
        if doc_id:
            doc_uuid = uuid_mod.UUID(doc_id)
            sug_ids = [
                r[0]
                for r in (
                    await db.execute(
                        select(Suggestion.id).where(
                            Suggestion.document_id == doc_uuid
                        )
                    )
                ).all()
            ]
            if sug_ids:
                await db.execute(
                    delete(FeedbackPattern).where(
                        FeedbackPattern.suggestion_id.in_(sug_ids)
                    )
                )
                await db.execute(
                    delete(Suggestion).where(Suggestion.id.in_(sug_ids))
                )
            await db.execute(
                delete(DocumentHistory).where(DocumentHistory.doc_id == doc_uuid)
            )
            await db.execute(
                delete(DocumentChunk).where(DocumentChunk.document_id == doc_uuid)
            )
            # Borrar el archivo físico antes que el registro
            doc = (
                await db.execute(select(Document).where(Document.id == doc_uuid))
            ).scalar_one_or_none()
            if doc:
                try:
                    Path(doc.file_path).unlink(missing_ok=True)
                except OSError:
                    pass
                await db.delete(doc)
        if created_user_id:
            await db.execute(delete(User).where(User.id == created_user_id))
        await db.commit()


async def test_full_flow_upload_pipeline_approve(tmp_path):
    """Flujo completo: subir doc → nodos reales del pipeline → aprobar sugerencia."""
    if not await _db_available():
        pytest.skip("Postgres no disponible — se omite el test de integración")

    user, user_created = await _get_or_create_user()
    app.dependency_overrides[get_current_user] = lambda: user

    doc_id: str | None = None
    transport = ASGITransport(app=app)

    try:
        # ── 1. Upload vía API real (sin auto-curación en background) ──────
        with (
            # HU-22: el upload ahora encola en vez de llamar al pipeline directo
            patch("app.api.docs.enqueue_curation", new=AsyncMock()),
            patch("app.api.docs.settings") as mock_settings,
        ):
            mock_settings.UPLOAD_DIR = str(tmp_path)
            mock_settings.MAX_FILE_SIZE = 52_428_800

            async with AsyncClient(transport=transport, base_url="http://t") as c:
                resp = await c.post(
                    "/api/docs/upload",
                    files={
                        "file": ("integracion.txt", _DOC_TEXT.encode(), "text/plain")
                    },
                )
        assert resp.status_code == 201, resp.text
        doc_id = resp.json()["id"]
        # HU-23: el documento nace en cola de procesamiento
        assert resp.json()["status"] == "queued"

        # ── 2. Pipeline: nodos REALES, servicios externos mockeados ───────
        from app.agents.nodes import (
            chunk_and_embed_node,
            faq_generation_node,
            generate_suggestions_node,
            redundancy_detection_node,
            wait_human_approval_node,
        )

        fake_chunks = [
            {
                "chroma_id": f"{doc_id}_chunk_0",
                "chunk_index": 0,
                "text": _DOC_TEXT,
                "token_count": 60,
                "hash": f"integ-{doc_id[:8]}",
                "page_number": 0,
                "category": "curated",
            }
        ]

        state = {
            "document_ids": [doc_id],
            "documents_text": {},
            "chunks": [],
            "messages": [],
            "suggestions": [],
            "redundancy_findings": [],
            "inconsistency_findings": [],
            "terminology_map": {},
            "web_search_results": [],
            "error": None,
        }

        with (
            # ChromaDB/embeddings: externo — mockeado
            patch("app.agents.nodes.embed_chunks", return_value=fake_chunks),
            # Redundancia: requiere ChromaDB — sin pares
            patch(
                "app.rag.redundancy.detect_redundancy_bulk",
                new=AsyncMock(return_value=[]),
            ),
            # LLM: apagado — la FAQ usa la heurística real
            patch("app.agents.nodes._get_llm_for_node", return_value=None),
        ):
            state.update(await chunk_and_embed_node(state))
            assert len(state["chunks"]) == 1, state.get("error")

            state.update(await redundancy_detection_node(state))
            assert state["redundancy_findings"] == []

            state.update(await faq_generation_node(state))
            assert len(state["suggestions"]) >= 1

            state.update(await generate_suggestions_node(state) or {})
            await wait_human_approval_node(state)

        faq = state["suggestions"][0]
        assert faq["type"] == "faq"
        assert faq["generation_method"] == "heuristic"
        assert faq["confidence_score"] == 0.60

        # ── 3. La sugerencia es consultable y aprobable vía API real ──────
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            resp = await c.get(
                "/api/suggestions", params={"document_id": doc_id}
            )
            assert resp.status_code == 200
            items = resp.json()["items"]
            assert any(s["id"] == faq["id"] for s in items)

            resp = await c.post(f"/api/suggestions/{faq['id']}/approve")
            assert resp.status_code == 200, resp.text

            # El documento queda aprobado
            resp = await c.get(f"/api/docs/{doc_id}")
            assert resp.json()["status"] == "approved"

        # ── 4. Efectos persistentes: feedback y auditoría ─────────────────
        async with AsyncSessionLocal() as db:
            sug = (
                await db.execute(
                    select(Suggestion).where(
                        Suggestion.id == uuid_mod.UUID(faq["id"])
                    )
                )
            ).scalar_one()
            assert sug.status == SuggestionStatus.approved
            assert sug.reviewed_by == user.id

            fb = (
                await db.execute(
                    select(FeedbackPattern).where(
                        FeedbackPattern.suggestion_id == sug.id
                    )
                )
            ).scalar_one()
            assert fb.feedback_type == "approve"

            n_history = (
                await db.execute(
                    select(DocumentHistory).where(
                        DocumentHistory.doc_id == uuid_mod.UUID(doc_id)
                    )
                )
            ).scalars()
            assert len(list(n_history)) >= 1

    finally:
        app.dependency_overrides.pop(get_current_user, None)
        await _cleanup(doc_id, user.id if user_created else None)
