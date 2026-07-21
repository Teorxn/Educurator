"""
Tests de las historias de usuario HU-20 a HU-32.

Cubren los criterios de aceptación verificables sin base de datos real:
validaciones de schemas, cola de curación, cálculo de costos de tokens y
las reglas de negocio nuevas.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

pytestmark = pytest.mark.asyncio


# ── HU-29: registro con perfil académico ─────────────────────────────────────


class TestRegisterSchema:
    def test_requires_at_least_one_subject(self):
        """Criterio: al menos 1 materia es obligatoria."""
        from app.schemas.users import RegisterRequest

        with pytest.raises(ValidationError):
            RegisterRequest(
                email="docente@test.dev",
                password="unaclave123",
                full_name="Ana Docente",
                subjects=[],
            )

    def test_password_minimum_length(self):
        from app.schemas.users import RegisterRequest

        with pytest.raises(ValidationError):
            RegisterRequest(
                email="docente@test.dev",
                password="corta",
                full_name="Ana Docente",
                subjects=["Cálculo"],
            )

    def test_multivalue_fields_are_normalized(self):
        """Listas multi-valor: sin vacíos ni duplicados."""
        from app.schemas.users import RegisterRequest

        req = RegisterRequest(
            email="docente@test.dev",
            password="unaclave123",
            full_name="Ana Docente",
            subjects=["  Cálculo  ", "Cálculo", "", "Álgebra"],
            specialties=["  IA  "],
        )
        assert req.subjects == ["Cálculo", "Álgebra"]
        assert req.specialties == ["IA"]


class TestRoleSchema:
    def test_role_name_must_be_slug(self):
        from app.schemas.users import RoleCreateRequest

        with pytest.raises(ValidationError):
            RoleCreateRequest(name="Rol Con Espacios")

    def test_valid_role_name(self):
        from app.schemas.users import RoleCreateRequest

        role = RoleCreateRequest(name="coordinador_academico", description="X")
        assert role.name == "coordinador_academico"


# ── HU-23: estados del procesamiento ─────────────────────────────────────────


class TestDocumentStatuses:
    def test_new_processing_states_exist(self):
        """Criterio: En cola, Procesando, Analizado y Error."""
        from app.models.models import DocumentStatus

        for value in ("queued", "processing", "analyzed", "error"):
            assert DocumentStatus(value).value == value

    async def test_queue_sets_status_and_enqueues(self):
        """enqueue_curation marca 'queued' y encola el documento."""
        from app.services import curation_queue

        doc_id = str(uuid.uuid4())
        with (
            patch.object(curation_queue, "_set_status", new=AsyncMock()) as mock_set,
            patch.object(curation_queue, "start_worker") as mock_start,
        ):
            await curation_queue.enqueue_curation(doc_id)

        mock_start.assert_called_once()
        assert mock_set.await_args.args[0] == doc_id
        assert curation_queue.get_queue().qsize() >= 1
        # limpiar la cola para no afectar otros tests
        while not curation_queue.get_queue().empty():
            curation_queue.get_queue().get_nowait()
            curation_queue.get_queue().task_done()

    async def test_pipeline_failure_marks_error_with_message(self):
        """Criterio: el estado Error muestra un mensaje descriptivo."""
        from app.models.models import DocumentStatus
        from app.services import curation_queue

        doc_id = str(uuid.uuid4())
        calls = []

        async def fake_set(d, status, *, error_message=None):
            calls.append((status, error_message))

        with (
            patch.object(curation_queue, "_set_status", new=fake_set),
            patch(
                "app.agents.graph.run_curation",
                new=AsyncMock(side_effect=ValueError("PDF corrupto")),
            ),
        ):
            await curation_queue._process_one(doc_id)

        assert calls[0][0] == DocumentStatus.processing
        assert calls[-1][0] == DocumentStatus.error
        assert "PDF corrupto" in (calls[-1][1] or "")

    async def test_successful_pipeline_marks_analyzed(self):
        from app.models.models import DocumentStatus
        from app.services import curation_queue

        calls = []

        async def fake_set(d, status, *, error_message=None):
            calls.append(status)

        with (
            patch.object(curation_queue, "_set_status", new=fake_set),
            patch("app.agents.graph.run_curation", new=AsyncMock(return_value={})),
        ):
            await curation_queue._process_one(str(uuid.uuid4()))

        assert calls == [DocumentStatus.processing, DocumentStatus.analyzed]


# ── HU-32: consumo de tokens y costo estimado ────────────────────────────────


class TestTokenAccounting:
    def test_cost_uses_configured_rates(self):
        from app.services.tokens import estimate_cost

        with patch("app.services.tokens.settings") as s:
            s.LLM_COST_PER_1K_INPUT_TOKENS = 0.001
            s.LLM_COST_PER_1K_OUTPUT_TOKENS = 0.002
            # 1000 in → 0.001 ; 500 out → 0.001 ; total 0.002
            assert estimate_cost(1000, 500) == pytest.approx(0.002)

    def test_uses_provider_usage_when_available(self):
        """Si el proveedor reporta uso real, se prefiere sobre la estimación."""
        from app.services.tokens import extract_usage

        response = MagicMock()
        response.usage_metadata = {"input_tokens": 120, "output_tokens": 45}
        assert extract_usage(response, "texto") == (120, 45)

    def test_falls_back_to_tiktoken_estimate(self):
        from app.services.tokens import extract_usage

        response = MagicMock()
        response.usage_metadata = {}
        response.content = "una respuesta del modelo"
        input_tokens, output_tokens = extract_usage(response, "pregunta larga")
        assert input_tokens > 0 and output_tokens > 0

    async def test_record_usage_skips_when_no_tokens(self):
        from app.services.tokens import record_usage

        with patch("app.database.AsyncSessionLocal") as factory:
            await record_usage(
                operation="chat", model="m", input_tokens=0, output_tokens=0
            )
        factory.assert_not_called()


# ── HU-22: carga múltiple ────────────────────────────────────────────────────


class TestBatchUpload:
    def test_batch_response_separates_valid_and_invalid(self):
        from app.schemas.docs import BatchUploadError, BatchUploadResponse

        resp = BatchUploadResponse(
            uploaded=[],
            failed=[BatchUploadError(filename="malo.exe", error="Tipo no soportado")],
            total_received=3,
            total_queued=2,
        )
        assert resp.total_received == 3
        assert resp.failed[0].filename == "malo.exe"

    def test_batch_limit_setting_exists(self):
        """Criterio: máximo 10 documentos por batch."""
        from app.config import settings

        assert settings.MAX_BATCH_UPLOAD == 10


# ── HU-31: chat fundamentado en RAG ──────────────────────────────────────────


class TestChatGrounding:
    async def test_no_documents_returns_no_context(self):
        """Sin documentos del usuario no se llama al LLM ni se inventa nada."""
        from app.api.chat import ChatRequest, chat

        db = AsyncMock()
        result = MagicMock()
        result.all.return_value = []
        db.execute = AsyncMock(return_value=result)

        user = MagicMock(id=uuid.uuid4())
        user.role = "instructor"

        resp = await chat(ChatRequest(question="¿Cuánto dura el curso?"), db, user)
        assert resp.has_context is False
        assert resp.sources == []
        assert "no encontré información" in resp.answer.lower()

    async def test_irrelevant_chunks_do_not_reach_llm(self):
        """Si ningún chunk supera el umbral, se responde sin contexto."""
        from app.api.chat import ChatRequest, chat

        doc_id = uuid.uuid4()
        db = AsyncMock()
        result = MagicMock()
        result.all.return_value = [(doc_id, "curso.pdf")]
        db.execute = AsyncMock(return_value=result)

        user = MagicMock(id=uuid.uuid4())
        user.role = "instructor"

        low_relevance = [
            {
                "chunk_id": f"{doc_id}_chunk_0",
                "doc_id": str(doc_id),
                "chunk_index": 0,
                "content": "contenido no relacionado",
                "similarity": 0.05,
            }
        ]
        with (
            patch("app.api.chat._retrieve_chunks", return_value=low_relevance),
            patch("app.agents.graph.get_llm") as mock_llm,
        ):
            resp = await chat(ChatRequest(question="pregunta ajena"), db, user)

        assert resp.has_context is False
        mock_llm.assert_not_called()


# ── HU-28: paginación de sugerencias ─────────────────────────────────────────


class TestSuggestionsPagination:
    def test_list_endpoint_accepts_page_and_limit(self):
        """El backend ya soporta skip/limit vía page & limit."""
        import inspect

        from app.api.suggestions import list_suggestions

        params = inspect.signature(list_suggestions).parameters
        assert "page" in params and "limit" in params


# ── HU-26: identidad del revisor ─────────────────────────────────────────────


class TestReviewerIdentity:
    def test_response_exposes_reviewer_fields(self):
        from app.schemas.suggestions import SuggestionResponse

        fields = SuggestionResponse.model_fields
        assert "reviewed_by_email" in fields
        assert "reviewed_by_name" in fields
        assert "reviewed_at" in fields
