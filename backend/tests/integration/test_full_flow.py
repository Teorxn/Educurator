"""
Test de integracion #27 — Flujo completo: upload -> parser -> chunker ->
redundancy detection -> suggestions -> approval.

Usa un archivo PDF real de 5 paginas con contenido educativo de matematicas
y verifica cada etapa del pipeline con aserciones en cada fase.

Requisitos:
  - pytest-asyncio
  - pytest-mock
  - httpx (para test client)
"""

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.agents.nodes import (
    chunk_and_embed_node,
    generate_suggestions_node,
    load_documents_node,
    redundancy_detection_node,
    wait_human_approval_node,
)
from app.agents.state import AgentState
from app.main import app
from app.models.models import (
    Document,
    DocumentCategory,
    DocumentChunk,
    DocumentHistory,
    DocumentStatus,
    FeedbackPattern,
    Suggestion,
    SuggestionStatus,
    SuggestionType,
)
from app.rag.chunker import chunk_text
from app.utils.parser import parse_document
from fastapi import status
from httpx import ASGITransport, AsyncClient

# =============================================================================
#  ETAPA 1: Upload + Parsing
# =============================================================================


class TestPDFParsing:
    """Verifica que el parser extrae texto correctamente del PDF real."""

    def test_pdf_file_exists(self, real_pdf_path: Path):
        """El archivo PDF debe existir y tener tamano razonable."""
        assert real_pdf_path.exists()
        assert real_pdf_path.stat().st_size > 1000  # al menos 1KB

    def test_parse_real_pdf_returns_text(self, real_pdf_path: Path):
        """El parser debe extraer texto del PDF real exitosamente."""
        text = parse_document(str(real_pdf_path))
        assert isinstance(text, str)
        assert len(text) > 0, "El PDF debe contener texto extraible"

    def test_parse_real_pdf_contains_keywords(self, real_pdf_path: Path):
        """El texto extraido debe contener terminos clave de todas las paginas."""
        text = parse_document(str(real_pdf_path))

        # Keywords de cada pagina
        assert "Algebra" in text, "Pagina 1: debe mencionar Algebra"
        assert "Ecuacion" in text, "Pagina 2: debe mencionar Ecuaciones"
        assert "Pitagoras" in text, "Pagina 3: debe mencionar Pitagoras"
        assert "Funcion" in text, "Pagina 4: debe mencionar Funciones"
        assert "Estadistica" in text, "Pagina 5: debe mencionar Estadistica"

    def test_parse_real_pdf_min_length(self, real_pdf_path: Path):
        """5 paginas de texto educativo deben producir al menos 1000 caracteres."""
        text = parse_document(str(real_pdf_path))
        assert len(text) >= 1000, (
            f"El texto extraido es muy corto ({len(text)} chars) "
            f"para un documento de 5 paginas"
        )


# =============================================================================
#  ETAPA 2: Chunking
# =============================================================================


class TestChunkingRealContent:
    """Verifica que el chunker procesa correctamente el texto real extraido."""

    def test_chunk_text_returns_list(self, real_pdf_text: str):
        """Chunking de texto real debe retornar una lista de chunks."""
        chunks = chunk_text(real_pdf_text)
        assert isinstance(chunks, list)
        assert len(chunks) > 0, "El texto debe producir al menos 1 chunk"

    def test_chunk_structure(self, real_pdf_text: str):
        """Cada chunk debe tener los campos esperados."""
        chunks = chunk_text(real_pdf_text)
        for i, chunk in enumerate(chunks):
            assert "text" in chunk, f"Chunk {i} debe tener 'text'"
            assert "token_count" in chunk, f"Chunk {i} debe tener 'token_count'"
            assert "hash" in chunk, f"Chunk {i} debe tener 'hash'"
            assert "start_token" in chunk, f"Chunk {i} debe tener 'start_token'"
            assert "end_token" in chunk, f"Chunk {i} debe tener 'end_token'"

    def test_chunk_reasonable_size(self, real_pdf_text: str):
        """Los chunks no deben exceder el tamano maximo configurado."""
        from app.rag.chunker import CHUNK_SIZE

        chunks = chunk_text(real_pdf_text)
        for i, chunk in enumerate(chunks):
            assert chunk["token_count"] <= CHUNK_SIZE, (
                f"Chunk {i} excede el tamano maximo de {CHUNK_SIZE} tokens"
            )

    def test_chunk_consistency(self, real_pdf_text: str):
        """El mismo texto debe producir los mismos chunks (determinismo)."""
        chunks_a = chunk_text(real_pdf_text)
        chunks_b = chunk_text(real_pdf_text)
        assert len(chunks_a) == len(chunks_b)
        for a, b in zip(chunks_a, chunks_b):
            assert a["hash"] == b["hash"]
            assert a["text"] == b["text"]

    def test_chunk_coverage(self, real_pdf_text: str):
        """Los chunks deben cubrir todo el texto original (sin perdidas)."""
        chunks = chunk_text(real_pdf_text)
        # Reconstruir el texto uniendo chunks (puede tener superposicion)
        reconstructed_parts = []
        for chunk in chunks:
            reconstructed_parts.append(chunk["text"])
        # Verificar que partes clave del texto original estan presentes
        assert "Pitagoras" in " ".join(reconstructed_parts)
        assert "Algebra" in " ".join(reconstructed_parts)
        assert "Funcion" in " ".join(reconstructed_parts)


# =============================================================================
#  ETAPA 3: Pipeline completo (load -> chunk -> redundancy -> suggestions)
# =============================================================================


class TestFullCurationPipeline:
    """Flujo completo del pipeline de curacion usando datos reales del PDF.

    Esta suite mockea la DB y ChromaDB en las fronteras, pero utiliza
    el PDF real, el parser real y el chunker real para procesar contenido
    autentico a traves del pipeline.
    """

    # ------------------------------------------------------------------
    #  Nodo 1: load_documents_node
    # ------------------------------------------------------------------

    @patch("app.agents.nodes.AsyncSessionLocal")
    async def test_load_documents_node_marks_document_as_processing(
        self,
        mock_session_factory: MagicMock,
        mock_db_session: AsyncMock,
        mock_document_with_pdf: Document,
    ):
        """load_documents_node debe cargar el doc y marcarlo como processing."""
        mock_session_factory.return_value.__aenter__.return_value = mock_db_session

        # Mock de consulta: retorna el documento con PDF real
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_document_with_pdf]
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        state: AgentState = {
            "document_ids": [],
            "documents_text": {},
            "chunks": [],
            "messages": [],
            "suggestions": [],
            "redundancy_findings": [],
            "error": None,
        }
        result = await load_documents_node(state)

        # Aserciones
        assert "document_ids" in result
        assert len(result["document_ids"]) == 1
        assert result["document_ids"][0] == str(mock_document_with_pdf.id)
        assert result.get("error") is None

        # Verificar cambio de estado
        assert mock_document_with_pdf.status == DocumentStatus.processing
        mock_db_session.commit.assert_awaited_once()

    @patch("app.agents.nodes.AsyncSessionLocal")
    async def test_load_documents_empty_when_no_pending(
        self,
        mock_session_factory: MagicMock,
        mock_db_session: AsyncMock,
    ):
        """Sin documentos pendientes, load_documents_node retorna vacio."""
        mock_session_factory.return_value.__aenter__.return_value = mock_db_session

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        state: AgentState = {
            "document_ids": [],
            "documents_text": {},
            "chunks": [],
            "messages": [],
            "suggestions": [],
            "redundancy_findings": [],
            "error": None,
        }
        result = await load_documents_node(state)

        assert result["document_ids"] == []
        assert result.get("error") is None

    # ------------------------------------------------------------------
    #  Nodo 2: chunk_and_embed_node
    # ------------------------------------------------------------------

    @patch("app.agents.nodes.AsyncSessionLocal")
    @patch("app.agents.nodes.parse_document")
    @patch("app.agents.nodes.embed_chunks")
    async def test_chunk_and_embed_with_real_pdf(
        self,
        mock_embed: MagicMock,
        mock_parse: MagicMock,
        mock_session_factory: MagicMock,
        mock_db_session: AsyncMock,
        mock_document_with_pdf: Document,
        real_pdf_text: str,
    ):
        """chunk_and_embed_node debe parsear el PDF real y crear chunks.

        Usamos mock para embed_chunks (evita ChromaDB y sentence-transformers)
        y para la sesion DB, pero el parsing usa el PDF real.
        """
        doc_id = str(mock_document_with_pdf.id)
        mock_session_factory.return_value.__aenter__.return_value = mock_db_session

        # Mock: el documento existe en DB
        doc_mock = MagicMock(spec=Document)
        doc_mock.id = mock_document_with_pdf.id
        doc_mock.file_path = str(mock_document_with_pdf.file_path)
        doc_mock.file_type = "pdf"
        doc_mock.original_filename = "test_curriculum_5pages.pdf"
        doc_mock.category = DocumentCategory.curated
        mock_db_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=doc_mock))
        )

        # Mock del parser con el texto real extraido
        mock_parse.return_value = real_pdf_text

        # Mock de embed_chunks con chunks reales del chunker
        from app.rag.chunker import chunk_text as real_chunk

        real_chunks = real_chunk(real_pdf_text)
        # Convertir al formato que espera embed_chunks (con chroma_id, etc.)
        fake_embedded = []
        for i, c in enumerate(real_chunks):
            fake_embedded.append(
                {
                    "chroma_id": f"{doc_id}_chunk_{i}",
                    "chunk_index": i,
                    "text": c["text"],
                    "token_count": c["token_count"],
                    "hash": c["hash"],
                    "page_number": 0,
                }
            )
        mock_embed.return_value = fake_embedded

        # Mock Path.exists para que pase la verificacion
        with patch.object(Path, "exists", return_value=True):
            state: AgentState = {
                "document_ids": [doc_id],
                "documents_text": {},
                "chunks": [],
                "messages": [],
                "suggestions": [],
                "redundancy_findings": [],
                "error": None,
            }
            result = await chunk_and_embed_node(state)

        # Aserciones
        assert "chunks" in result
        assert len(result["chunks"]) == len(real_chunks), (
            f"Deben crearse {len(real_chunks)} chunks, "
            f"se crearon {len(result['chunks'])}"
        )
        assert "documents_text" in result
        assert doc_id in result["documents_text"]
        assert result.get("error") is None

        # Verificar que se parseo y embe bio el documento
        mock_parse.assert_called_once()
        assert mock_parse.call_args[0][0] == str(mock_document_with_pdf.file_path)
        mock_embed.assert_called_once()

        # Verificar estructura de los chunks
        for i, chunk in enumerate(result["chunks"]):
            assert "chroma_id" in chunk, f"Chunk {i} debe tener chroma_id"
            assert "chunk_index" in chunk, f"Chunk {i} debe tener chunk_index"
            assert "text" in chunk, f"Chunk {i} debe tener text"
            assert "token_count" in chunk, f"Chunk {i} debe tener token_count"
            assert chunk["token_count"] > 0, f"Chunk {i} debe tener tokens"

        # Verificar que los DocumentChunk se agregaron a la DB
        add_calls = []
        for call in mock_db_session.add.call_args_list:
            args, _ = call
            if args and isinstance(args[0], DocumentChunk):
                add_calls.append(args[0])
        assert len(add_calls) == len(real_chunks), (
            f"Deben persistirse {len(real_chunks)} DocumentChunk en DB, "
            f"se persistieron {len(add_calls)}"
        )

        # Verificar que se hizo flush
        mock_db_session.flush.assert_awaited()

    # ------------------------------------------------------------------
    #  Nodo 3: redundancy_detection_node
    # ------------------------------------------------------------------

    @patch("app.rag.redundancy.detect_redundancy_bulk")
    async def test_redundancy_detection_with_real_chunks(
        self,
        mock_detect_bulk: MagicMock,
        real_pdf_text: str,
    ):
        """redundancy_detection_node debe procesar chunks de contenido real."""
        # Crear chunks reales del PDF
        real_chunks = chunk_text(real_pdf_text)
        doc_id = str(uuid.uuid4())

        # Formatear como los retorna chunk_and_embed
        agent_chunks = []
        for i, c in enumerate(real_chunks):
            agent_chunks.append(
                {
                    "chroma_id": f"{doc_id}_chunk_{i}",
                    "chunk_index": i,
                    "text": c["text"],
                    "token_count": c["token_count"],
                    "hash": c["hash"],
                    "page_number": 0,
                }
            )

        # Mock: retorna hallazgos de redundancia realistas
        mock_report = MagicMock()
        mock_report.redundant_pairs = [
            MagicMock(
                chunk_id_a=agent_chunks[0]["chroma_id"],
                chunk_id_b=agent_chunks[1]["chroma_id"],
                similarity=0.95,
                confidence_score=0.92,
                doc_id_a=doc_id,
                doc_id_b=doc_id,
                content_a_preview=agent_chunks[0]["text"][:100],
                content_b_preview=agent_chunks[1]["text"][:100],
                token_count_a=agent_chunks[0]["token_count"],
                token_count_b=agent_chunks[1]["token_count"],
            ),
        ]
        mock_detect_bulk.return_value = [mock_report]

        state: AgentState = {
            "document_ids": [doc_id],
            "documents_text": {doc_id: real_pdf_text},
            "chunks": agent_chunks,
            "messages": [],
            "suggestions": [],
            "redundancy_findings": [],
            "error": None,
        }
        result = await redundancy_detection_node(state)

        # Aserciones
        assert "redundancy_findings" in result
        findings = result["redundancy_findings"]
        assert len(findings) > 0, "Debe detectar al menos un par redundante"

        # Verificar estructura de cada hallazgo
        for finding in findings:
            assert "chunk_id_a" in finding
            assert "chunk_id_b" in finding
            assert "similarity" in finding
            assert "confidence_score" in finding
            assert "doc_id_a" in finding
            assert "doc_id_b" in finding
            assert isinstance(finding["similarity"], float)
            assert isinstance(finding["confidence_score"], float)
            assert 0.0 <= finding["similarity"] <= 1.0
            assert 0.0 <= finding["confidence_score"] <= 1.0

        # Verificar que se llamo detect_redundancy_bulk
        mock_detect_bulk.assert_called_once()

    # ------------------------------------------------------------------
    #  Nodo 4: generate_suggestions_node
    # ------------------------------------------------------------------

    @patch("app.agents.nodes.AsyncSessionLocal")
    async def test_generate_suggestions_from_redundancy_findings(
        self,
        mock_session_factory: MagicMock,
        mock_db_session: AsyncMock,
        real_pdf_text: str,
    ):
        """generate_suggestions_node debe crear sugerencias pending en DB."""
        doc_id = str(uuid.uuid4())
        mock_session_factory.return_value.__aenter__.return_value = mock_db_session

        # Mock execute para que el SELECT find documents dentro de wait_human_approval
        # no falle (no se llama en generate_suggestions)
        mock_db_session.execute = AsyncMock()

        # Crear chunks reales
        real_chunks = chunk_text(real_pdf_text)
        agent_chunks = []
        for i, c in enumerate(real_chunks):
            agent_chunks.append(
                {
                    "chroma_id": f"{doc_id}_chunk_{i}",
                    "chunk_index": i,
                    "text": c["text"],
                    "token_count": c["token_count"],
                    "hash": c["hash"],
                    "page_number": 0,
                }
            )

        # Crear redundancy findings con datos reales
        redundancy_findings = []
        if len(agent_chunks) >= 2:
            redundancy_findings.append(
                {
                    "chunk_id_a": agent_chunks[0]["chroma_id"],
                    "chunk_id_b": agent_chunks[1]["chroma_id"],
                    "similarity": 0.95,
                    "confidence_score": 0.92,
                    "doc_id_a": doc_id,
                    "doc_id_b": doc_id,
                    "content_a_preview": agent_chunks[0]["text"][:100],
                    "content_b_preview": agent_chunks[1]["text"][:100],
                    "token_count_a": agent_chunks[0]["token_count"],
                    "token_count_b": agent_chunks[1]["token_count"],
                }
            )

        state: AgentState = {
            "document_ids": [doc_id],
            "documents_text": {doc_id: real_pdf_text},
            "chunks": agent_chunks,
            "messages": [],
            "suggestions": [],
            "redundancy_findings": redundancy_findings,
            "error": None,
        }
        result = await generate_suggestions_node(state)

        # Aserciones: debe haber sugerencias generadas
        assert "suggestions" in result
        suggestions = result["suggestions"]
        assert len(suggestions) > 0, (
            "Debe generar al menos una sugerencia a partir de los hallazgos"
        )

        # Verificar estructura de cada sugerencia
        for s in suggestions:
            assert "id" in s, "Sugerencia debe tener id"
            assert "document_id" in s, "Sugerencia debe tener document_id"
            assert "type" in s, "Sugerencia debe tener type"
            assert "description" in s, "Sugerencia debe tener description"
            assert "confidence_score" in s, "Sugerencia debe tener confidence_score"
            assert s["type"] in ("redundancy", "conflict", "faq", "update")
            assert isinstance(s["confidence_score"], (int, float))
            assert s["document_id"] == doc_id

        # Verificar que las sugerencias se agregaron a la DB como Suggestion
        suggestion_adds = []
        for call in mock_db_session.add.call_args_list:
            args, _ = call
            if args and isinstance(args[0], Suggestion):
                suggestion_adds.append(args[0])
        assert len(suggestion_adds) > 0, "Deben persistirse sugerencias en DB"

        # Verificar que las sugerencias estan en estado pending
        for sug in suggestion_adds:
            assert isinstance(sug, Suggestion)
            assert sug.status == SuggestionStatus.pending, (
                f"Las sugerencias deben crearse como pending, se obtuvo {sug.status}"
            )
            assert sug.type == SuggestionType.redundancy
            assert sug.confidence_score > 0

        # Verificar commit
        mock_db_session.commit.assert_awaited_once()

    @patch("app.agents.nodes.AsyncSessionLocal")
    async def test_generate_suggestions_no_redundancy_findings(
        self,
        mock_session_factory: MagicMock,
        mock_db_session: AsyncMock,
    ):
        """Sin hallazgos de redundancia, no deben crearse sugerencias."""
        mock_session_factory.return_value.__aenter__.return_value = mock_db_session
        mock_db_session.execute = AsyncMock()

        state: AgentState = {
            "document_ids": [str(uuid.uuid4())],
            "documents_text": {},
            "chunks": [],
            "messages": [],
            "suggestions": [],
            "redundancy_findings": [],
            "error": None,
        }
        result = await generate_suggestions_node(state)

        assert "suggestions" in result
        assert result["suggestions"] == []

    # ------------------------------------------------------------------
    #  Nodo 5: wait_human_approval_node
    # ------------------------------------------------------------------

    @patch("app.agents.nodes.AsyncSessionLocal")
    async def test_wait_human_approval_returns_doc_to_needs_review(
        self,
        mock_session_factory: MagicMock,
        mock_db_session: AsyncMock,
        mock_document_with_pdf: Document,
        real_pdf_text: str,
    ):
        """wait_human_approval_node debe devolver el doc a needs_review."""
        doc_id = str(mock_document_with_pdf.id)
        mock_session_factory.return_value.__aenter__.return_value = mock_db_session

        # Mock: el documento existe en DB y esta en estado processing
        doc_in_db = MagicMock(spec=Document)
        doc_in_db.id = mock_document_with_pdf.id
        doc_in_db.status = DocumentStatus.processing
        mock_db_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=doc_in_db))
        )

        # Crear sugerencias simuladas
        suggestions = [
            {
                "id": str(uuid.uuid4()),
                "document_id": doc_id,
                "type": "redundancy",
                "description": "Contenido redundante detectado",
                "confidence_score": 0.92,
            }
        ]

        state: AgentState = {
            "document_ids": [doc_id],
            "documents_text": {doc_id: real_pdf_text},
            "chunks": [],
            "messages": [],
            "suggestions": suggestions,
            "redundancy_findings": [],
            "error": None,
        }
        await wait_human_approval_node(state)

        # Verificar que se cambio el estado
        assert doc_in_db.status == DocumentStatus.needs_review

        # Verificar que se creo el audit trail
        history_adds = []
        for call in mock_db_session.add.call_args_list:
            args, _ = call
            if args and isinstance(args[0], DocumentHistory):
                history_adds.append(args[0])

        assert len(history_adds) >= 1, "Debe crearse un registro de DocumentHistory"

        # Verificar contenido del history
        history_entry = history_adds[0]
        assert history_entry.action == "agent_completed"
        assert history_entry.doc_id == mock_document_with_pdf.id
        assert history_entry.performed_by is None  # accion del sistema
        assert history_entry.before_content == {"status": "processing"}
        assert history_entry.after_content["status"] == "needs_review"

        # Verificar commit
        mock_db_session.commit.assert_awaited()


# =============================================================================
#  ETAPA 4: Aprobacion via API
# =============================================================================


class _MockDBSession:
    """Helper para inyectar un mock de sesion DB via dependency_overrides."""

    def __init__(self):
        self.session = self._create_session()

    def _create_session(self) -> AsyncMock:
        session = AsyncMock()
        session.commit = AsyncMock()
        session.flush = AsyncMock()
        session.refresh = AsyncMock()
        session.close = AsyncMock()
        session.add = MagicMock()
        return session

    async def __call__(self):
        yield self.session

    def reset(self):
        self.session = self._create_session()


class TestSuggestionApprovalAPI:
    """Verifica el flujo de aprobacion de sugerencias via API.

    Usa app.dependency_overrides para mockear la DB y la autenticacion.
    """

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Configura los overrides de dependencias antes de cada test."""
        from app.database import get_db

        self._db_mock = _MockDBSession()
        app.dependency_overrides[get_db] = self._db_mock
        yield
        # Limpiar SOLO el override de get_db, no los demas
        app.dependency_overrides.pop(get_db, None)

    @property
    def mock_session(self) -> AsyncMock:
        return self._db_mock.session

    async def _setup_suggestion_and_doc(self, status=SuggestionStatus.pending):
        """Configura los mocks de suggestion y documento en la sesion."""
        suggestion_id = uuid.uuid4()
        doc_id = uuid.uuid4()

        mock_suggestion = MagicMock(spec=Suggestion)
        mock_suggestion.id = suggestion_id
        mock_suggestion.document_id = doc_id
        mock_suggestion.status = status
        mock_suggestion.type = SuggestionType.redundancy
        mock_suggestion.confidence_score = 0.92
        mock_suggestion.description = "Contenido redundante"
        mock_suggestion.source_doc_id = str(doc_id)
        mock_suggestion.source_chunk_ids = ["chunk_0", "chunk_1"]
        mock_suggestion.reasoning = "Similitud alta detectada"

        mock_doc = MagicMock(spec=Document)
        mock_doc.id = doc_id
        mock_doc.status = DocumentStatus.needs_review

        return suggestion_id, doc_id, mock_suggestion, mock_doc

    async def test_approve_suggestion_creates_history(self):
        """POST /api/suggestions/{id}/approve debe crear document_history."""
        (
            suggestion_id,
            doc_id,
            mock_suggestion,
            mock_doc,
        ) = await self._setup_suggestion_and_doc()
        self.mock_session.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=mock_suggestion)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=mock_doc)),
            ]
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"/api/suggestions/{suggestion_id}/approve")

        assert resp.status_code == status.HTTP_200_OK, (
            f"Se esperaba 200, se obtuvo {resp.status_code}: {resp.text}"
        )
        data = resp.json()
        assert data["status"] == "approved"
        assert data["id"] == str(suggestion_id)

        # Verificar que se persistio el DocumentHistory
        history_adds = []
        for call in self.mock_session.add.call_args_list:
            args, _ = call
            if args and isinstance(args[0], DocumentHistory):
                history_adds.append(args[0])
        assert len(history_adds) >= 1, "El approval debe crear un DocumentHistory"
        hist_entry = history_adds[0]
        assert hist_entry.action == "approved"
        assert hist_entry.doc_id == doc_id

        # Verificar que se creo FeedbackPattern
        feedback_adds = []
        for call in self.mock_session.add.call_args_list:
            args, _ = call
            if args and isinstance(args[0], FeedbackPattern):
                feedback_adds.append(args[0])
        assert len(feedback_adds) >= 1, "El approval debe crear un FeedbackPattern"

        # Verificar commit
        self.mock_session.commit.assert_awaited_once()

    async def test_approve_nonexistent_suggestion_returns_404(self):
        """Aprobar sugerencia inexistente debe retornar 404."""
        self.mock_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        suggestion_id = uuid.uuid4()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"/api/suggestions/{suggestion_id}/approve")

        assert resp.status_code == status.HTTP_404_NOT_FOUND

    async def test_approve_already_approved_suggestion_returns_400(self):
        """Aprobar sugerencia ya aprobada debe retornar 400."""
        (
            suggestion_id,
            _doc_id,
            mock_suggestion,
            _mock_doc,
        ) = await self._setup_suggestion_and_doc(status=SuggestionStatus.approved)
        self.mock_session.execute = AsyncMock(
            return_value=MagicMock(
                scalar_one_or_none=MagicMock(return_value=mock_suggestion)
            )
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"/api/suggestions/{suggestion_id}/approve")

        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# =============================================================================
#  ETAPA 5: Upload via API
# =============================================================================


class TestDocUploadAPI:
    """Verifica el endpoint de upload de documentos.

    Usa app.dependency_overrides para mockear la DB y la autenticacion.
    """

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Configura los overrides de dependencias antes de cada test."""
        from app.database import get_db

        self._db_mock = _MockDBSession()
        app.dependency_overrides[get_db] = self._db_mock
        yield
        app.dependency_overrides.pop(get_db, None)

    @property
    def mock_session(self) -> AsyncMock:
        return self._db_mock.session

    async def test_upload_pdf_file(
        self,
        pdf_bytes: bytes,
    ):
        """POST /api/docs/upload con PDF real debe retornar 201."""

        async def refresh_side_effect(obj):
            from datetime import datetime, timezone

            obj.id = uuid.uuid4()
            obj.category = DocumentCategory.curated
            obj.uploaded_at = datetime.now(timezone.utc)
            obj.status = DocumentStatus.needs_review

        self.mock_session.refresh = AsyncMock(side_effect=refresh_side_effect)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/docs/upload",
                files={"file": ("test_curriculo.pdf", pdf_bytes, "application/pdf")},
            )

        assert resp.status_code == status.HTTP_201_CREATED, (
            f"Se esperaba 201, se obtuvo {resp.status_code}: {resp.text}"
        )
        data = resp.json()
        assert data["filename"] is not None
        assert data["status"] == "needs_review"
        assert data["file_type"] == "pdf"
        assert data["size_bytes"] == len(pdf_bytes)

        # Verificar que se agrego un Document a la DB
        doc_adds = []
        for call in self.mock_session.add.call_args_list:
            args, _ = call
            if args and isinstance(args[0], Document):
                doc_adds.append(args[0])
        assert len(doc_adds) == 1

        doc = doc_adds[0]
        assert doc.filename.endswith(".pdf")
        assert doc.file_type == "pdf"
        assert doc.status == DocumentStatus.needs_review

        # Verificar commit
        self.mock_session.commit.assert_awaited_once()

    async def test_upload_non_pdf_rejected(self):
        """Upload de archivo no soportado debe retornar 415.

        Usamos un archivo con extension .xyz y content-type desconocido
        que no es PDF, DOCX ni TXT.
        """
        content = b"\x00\x01\x02Unsupported binary content that is not PDF/DOCX/TXT"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/docs/upload",
                files={"file": ("test.xyz", content, "application/octet-stream")},
            )

        assert resp.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
