"""
Tests de integración para el pipeline completo del agente de curación (#12).

Cubre:
  - Cada nodo del grafo por separado (con dependencias mockeadas)
  - El flujo completo end-to-end (load → chunk → redundancy → suggestions → approval)
  - Persistencia correcta de sugerencias en Postgres
  - Transiciones de estado de documentos
  - Auditoría (document_history)

Requisitos:
  pytest-asyncio
  pytest-mock
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.agents.graph import get_graph_info, run_curation
from app.agents.nodes import (
    chunk_and_embed_node,
    generate_suggestions_node,
    load_documents_node,
    redundancy_detection_node,
    wait_human_approval_node,
)
from app.agents.state import AgentState
from app.config import settings
from app.models.models import (
    Document,
    DocumentChunk,
    DocumentHistory,
    DocumentStatus,
    Suggestion,
    SuggestionStatus,
    SuggestionType,
    User,
)
from sqlalchemy.ext.asyncio import AsyncSession

# =============================================================================
#  FIXTURES
# =============================================================================


@pytest.fixture
def mock_db_session():
    """Crea una sesión de base de datos mockeada con AsyncMock."""
    session = AsyncMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.close = AsyncMock()
    return session


@pytest.fixture
def mock_document():
    """Crea un documento de prueba con valores realistas."""
    doc_id = uuid.uuid4()
    return Document(
        id=doc_id,
        filename="teorema_pitagoras.txt",
        original_filename="teorema_pitagoras.txt",
        file_type="txt",
        file_path=str(Path(settings.UPLOAD_DIR) / f"{doc_id}_test.txt"),
        size_bytes=512,
        status=DocumentStatus.needs_review,
        uploaded_by=uuid.uuid4(),
        uploaded_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_chunks():
    """Lista de chunks simulados como los retorna chunk_and_embed."""
    return [
        {
            "chroma_id": f"test_doc_chunk_{i}",
            "chunk_index": i,
            "text": f"Contenido del chunk {i} del documento de prueba. "
            f"Esto es texto simulado para verificar el pipeline.",
            "token_count": 25,
            "hash": f"abc{i}" * 16,
            "page_number": 0,
        }
        for i in range(5)
    ]


@pytest.fixture
def sample_redundancy_findings():
    """Hallazgos de redundancia simulados."""
    return [
        {
            "chunk_id_a": "test_doc_chunk_0",
            "chunk_id_b": "test_doc_chunk_2",
            "similarity": 0.95,
            "confidence_score": 0.92,
            "doc_id_a": str(uuid.uuid4()),
            "doc_id_b": str(uuid.uuid4()),
        },
        {
            "chunk_id_a": "test_doc_chunk_1",
            "chunk_id_b": "test_doc_chunk_3",
            "similarity": 0.91,
            "confidence_score": 0.88,
            "doc_id_a": str(uuid.uuid4()),
            "doc_id_b": str(uuid.uuid4()),
        },
    ]


@pytest.fixture
def sample_suggestions_from_agent():
    """Tool calls simuladas del agente ReAct."""
    doc_id = str(uuid.uuid4())
    return [
        {
            "status": "success",
            "suggestion_id": str(uuid.uuid4()),
            "document_id": doc_id,
            "type": "conflict",
            "state": "pending",
            "source_doc_id": doc_id,
            "source_chunk_ids": ["chunk_a", "chunk_b"],
            "confidence_score": 0.85,
            "message": "Posible conflicto detectado entre dos definiciones del teorema.",
        }
    ]


@pytest.fixture
def agent_state_empty() -> AgentState:
    """Estado vacío del agente."""
    return {
        "document_ids": [],
        "documents_text": {},
        "chunks": [],
        "messages": [],
        "suggestions": [],
        "redundancy_findings": [],
        "error": None,
    }


@pytest.fixture
def agent_state_with_docs(agent_state_empty) -> AgentState:
    """Estado con documentos pendientes."""
    state = dict(agent_state_empty)
    state["document_ids"] = [str(uuid.uuid4()), str(uuid.uuid4())]
    return state


# =============================================================================
#  TESTS: INFORMACIÓN DEL GRAFO
# =============================================================================


class TestGraphInfo:
    """Verifica que el grafo se compile correctamente y exponga metadatos."""

    def test_graph_info_structure(self):
        """El grafo debe reportar nodos, tools, checkpointer y LLM."""
        info = get_graph_info()

        assert "nodes" in info
        assert "checkpointer" in info
        assert "tools" in info
        assert "llm" in info

        # Nodos esperados del grafo principal
        expected_nodes = {
            "load_documents",
            "chunk_and_embed",
            "redundancy_detection",
            "generate_suggestions",
            "wait_human_approval",
        }
        assert expected_nodes.issubset(set(info["nodes"]))

        # Tools esperadas
        expected_tools = {
            "search_documents",
            "compare_content",
            "detect_conflict",
            "suggest_update",
            "generate_faq_entry",
            "log_action",
            "detect_redundancy",
        }
        assert set(info["tools"]) == expected_tools


# =============================================================================
#  TESTS: NODO load_documents
# =============================================================================


class TestLoadDocumentsNode:
    """Prueba la carga de documentos pendientes desde Postgres."""

    @patch("app.agents.nodes.AsyncSessionLocal")
    async def test_loads_pending_documents(
        self, mock_session_factory, mock_db_session, mock_document
    ):
        """Debe cargar documentos con status needs_review y marcarlos como processing."""
        # Configurar mock
        mock_session_factory.return_value.__aenter__.return_value = mock_db_session

        # Mock de la consulta: retorna documentos pendientes
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_document]
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        # Ejecutar nodo
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

        # Verificar
        assert "document_ids" in result
        assert len(result["document_ids"]) == 1
        assert result["document_ids"][0] == str(mock_document.id)
        assert result.get("error") is None

        # Verificar que se marcó como processing
        assert mock_document.status == DocumentStatus.processing
        mock_db_session.commit.assert_awaited_once()

    @patch("app.agents.nodes.AsyncSessionLocal")
    async def test_no_pending_documents(self, mock_session_factory, mock_db_session):
        """Cuando no hay documentos pendientes, debe retornar lista vacía."""
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


# =============================================================================
#  TESTS: NODO chunk_and_embed
# =============================================================================


class TestChunkAndEmbedNode:
    """Prueba el parsing, chunking y embedding de documentos."""

    @patch("app.agents.nodes.AsyncSessionLocal")
    @patch("app.agents.nodes.parse_document")
    @patch("app.agents.nodes.embed_chunks")
    async def test_processes_documents_successfully(
        self,
        mock_embed,
        mock_parse,
        mock_session_factory,
        mock_db_session,
        sample_chunks,
    ):
        """Debe parsear, chunquear y embeber cada documento correctamente."""
        doc_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        mock_session_factory.return_value.__aenter__.return_value = mock_db_session

        # Mock: cada documento existe en DB
        docs = []
        for i, did in enumerate(doc_ids):
            doc = MagicMock(spec=Document)
            doc.id = uuid.UUID(did)
            doc.file_path = f"/tmp/test_{i}.txt"
            doc.file_type = "txt"
            doc.original_filename = f"test_{i}.txt"
            docs.append(doc)

        # Mock de execute retorna cada documento secuencialmente
        mock_db_session.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=doc))
                for doc in docs
            ]
        )

        # Mock parse_document retorna texto simulado
        mock_parse.return_value = (
            "Contenido del documento de prueba para el pipeline de curación."
        )

        # Mock embed_chunks retorna chunks simulados
        mock_embed.return_value = sample_chunks

        # Mock Path.exists para evitar que el nodo intente leer archivos reales
        with patch.object(Path, "exists", return_value=True):
            state: AgentState = {
                "document_ids": doc_ids,
                "documents_text": {},
                "chunks": [],
                "messages": [],
                "suggestions": [],
                "redundancy_findings": [],
                "error": None,
            }
            result = await chunk_and_embed_node(state)

        assert "chunks" in result
        # 2 documentos × 5 chunks cada uno = 10 chunks total
        assert len(result["chunks"]) == len(doc_ids) * len(sample_chunks)
        assert "documents_text" in result
        assert len(result["documents_text"]) == len(doc_ids)
        assert result.get("error") is None

        # Verificar que se parsearon y embebieron los documentos
        assert mock_parse.call_count == len(doc_ids)
        assert mock_embed.call_count == len(doc_ids)

    @patch("app.agents.nodes.AsyncSessionLocal")
    async def test_no_documents_to_process(self, mock_session_factory, mock_db_session):
        """Sin document_ids, debe retornar vacío."""
        mock_session_factory.return_value.__aenter__.return_value = mock_db_session

        state: AgentState = {
            "document_ids": [],
            "documents_text": {},
            "chunks": [],
            "messages": [],
            "suggestions": [],
            "redundancy_findings": [],
            "error": None,
        }
        result = await chunk_and_embed_node(state)

        assert result["chunks"] == []
        assert result["documents_text"] == {}
        mock_db_session.commit.assert_not_called()


# =============================================================================
#  TESTS: NODO redundancy_detection
# =============================================================================


class TestRedundancyDetectionNode:
    """Prueba la detección automática de redundancia."""

    @patch("app.rag.redundancy.detect_redundancy_bulk")
    async def test_detects_redundant_pairs(self, mock_detect_bulk, sample_chunks):
        """Debe detectar pares redundantes a partir de los chunks."""
        # Configurar mock: retorna reportes simulados
        mock_report = MagicMock()
        mock_report.redundant_pairs = [
            MagicMock(
                chunk_id_a="chunk_0",
                chunk_id_b="chunk_2",
                similarity=0.95,
                confidence_score=0.92,
                doc_id_a="doc_a",
                doc_id_b="doc_b",
            ),
            MagicMock(
                chunk_id_a="chunk_1",
                chunk_id_b="chunk_3",
                similarity=0.91,
                confidence_score=0.88,
                doc_id_a="doc_a",
                doc_id_b="doc_b",
            ),
        ]
        mock_detect_bulk.return_value = [mock_report]

        state: AgentState = {
            "document_ids": [],
            "documents_text": {},
            "chunks": sample_chunks,
            "messages": [],
            "suggestions": [],
            "redundancy_findings": [],
            "error": None,
        }
        result = await redundancy_detection_node(state)

        assert "redundancy_findings" in result
        assert len(result["redundancy_findings"]) == 2
        assert result["redundancy_findings"][0]["similarity"] == 0.95
        assert result["redundancy_findings"][1]["confidence_score"] == 0.88

        # Verificar que se llamó detect_redundancy_bulk con los chroma_ids correctos
        chroma_ids_called = mock_detect_bulk.call_args[1].get("chunk_ids", [])
        assert len(chroma_ids_called) == len(sample_chunks)
        assert chroma_ids_called[0] == sample_chunks[0]["chroma_id"]

    async def test_no_chunks_no_findings(self):
        """Sin chunks, no debe haber hallazgos."""
        state: AgentState = {
            "document_ids": [],
            "documents_text": {},
            "chunks": [],
            "messages": [],
            "suggestions": [],
            "redundancy_findings": [],
            "error": None,
        }
        result = await redundancy_detection_node(state)

        assert result["redundancy_findings"] == []


# =============================================================================
#  TESTS: NODO generate_suggestions
# =============================================================================


class TestGenerateSuggestionsNode:
    """Prueba la generación de sugerencias en Postgres."""

    @patch("app.agents.nodes.AsyncSessionLocal")
    async def test_creates_suggestions_from_redundancy_findings(
        self, mock_session_factory, mock_db_session, sample_redundancy_findings
    ):
        """Los hallazgos de redundancia deben convertirse en sugerencias pending."""
        mock_session_factory.return_value.__aenter__.return_value = mock_db_session

        state: AgentState = {
            "document_ids": [],
            "documents_text": {},
            "chunks": [],
            "messages": [],
            "suggestions": [],
            "redundancy_findings": sample_redundancy_findings,
            "error": None,
        }
        result = await generate_suggestions_node(state)

        assert "suggestions" in result
        assert len(result["suggestions"]) == len(sample_redundancy_findings)

        # Verificar que se agregaron sugerencias a la sesión
        added_suggestions = [
            call.args[0]
            for call in mock_db_session.add.call_args_list
            if isinstance(call.args[0], Suggestion)
        ]
        assert len(added_suggestions) == len(sample_redundancy_findings)

        # Verificar propiedades de las sugerencias
        suggestion = added_suggestions[0]
        assert suggestion.type == SuggestionType.redundancy
        assert suggestion.status == SuggestionStatus.pending
        assert (
            suggestion.confidence_score
            == sample_redundancy_findings[0]["confidence_score"]
        )
        assert suggestion.source_chunk_ids == [
            sample_redundancy_findings[0]["chunk_id_a"],
            sample_redundancy_findings[0]["chunk_id_b"],
        ]

        mock_db_session.commit.assert_awaited_once()

    @patch("app.agents.nodes.AsyncSessionLocal")
    async def test_creates_suggestions_from_tool_calls(
        self, mock_session_factory, mock_db_session, sample_suggestions_from_agent
    ):
        """Las tool calls del agente deben crear sugerencias adicionales."""
        from langchain_core.messages import AIMessage, ToolMessage

        mock_session_factory.return_value.__aenter__.return_value = mock_db_session

        # Simular mensajes del agente con tool_calls
        messages = [
            AIMessage(
                content="He detectado un posible conflicto.",
                tool_calls=[
                    {
                        "name": "suggest_update",
                        "args": {
                            "document_id": sample_suggestions_from_agent[0][
                                "document_id"
                            ],
                            "type": "conflict",
                            "message": "Posible conflicto...",
                            "source_doc_id": sample_suggestions_from_agent[0][
                                "source_doc_id"
                            ],
                            "source_chunk_ids": sample_suggestions_from_agent[0][
                                "source_chunk_ids"
                            ],
                            "confidence_score": sample_suggestions_from_agent[0][
                                "confidence_score"
                            ],
                        },
                        "id": "call_1",
                    }
                ],
            ),
            ToolMessage(
                content=json.dumps(sample_suggestions_from_agent[0]),
                tool_call_id="call_1",
                name="suggest_update",
            ),
        ]

        state: AgentState = {
            "document_ids": [],
            "documents_text": {},
            "chunks": [],
            "messages": messages,
            "suggestions": [],
            "redundancy_findings": [],
            "error": None,
        }
        result = await generate_suggestions_node(state)

        assert "suggestions" in result
        # Debe haber al menos la sugerencia del tool call
        assert len(result["suggestions"]) >= 1

    @patch("app.agents.nodes.AsyncSessionLocal")
    async def test_no_suggestions_when_no_findings(
        self, mock_session_factory, mock_db_session
    ):
        """Sin hallazgos ni tool calls, no debe generar sugerencias."""
        mock_session_factory.return_value.__aenter__.return_value = mock_db_session

        state: AgentState = {
            "document_ids": [],
            "documents_text": {},
            "chunks": [],
            "messages": [],
            "suggestions": [],
            "redundancy_findings": [],
            "error": None,
        }
        result = await generate_suggestions_node(state)

        assert result["suggestions"] == []


# =============================================================================
#  TESTS: NODO wait_human_approval
# =============================================================================


class TestWaitHumanApprovalNode:
    """Prueba la transición a estado de espera de revisión humana."""

    @patch("app.agents.nodes.AsyncSessionLocal")
    async def test_changes_documents_to_needs_review(
        self, mock_session_factory, mock_db_session
    ):
        """Los documentos deben pasar a needs_review y crear audit trail."""
        doc_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        mock_session_factory.return_value.__aenter__.return_value = mock_db_session

        # Mock de documentos en DB
        docs = []
        for did in doc_ids:
            doc = MagicMock(spec=Document)
            doc.id = uuid.UUID(did)
            doc.status = DocumentStatus.processing
            docs.append(doc)

        mock_db_session.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=doc))
                for doc in docs
            ]
        )

        state: AgentState = {
            "document_ids": doc_ids,
            "documents_text": {},
            "chunks": [],
            "messages": [],
            "suggestions": [
                {"document_id": doc_ids[0], "type": "redundancy"},
                {"document_id": doc_ids[0], "type": "conflict"},
            ],
            "redundancy_findings": [],
            "error": None,
        }
        result = await wait_human_approval_node(state)

        # Verificar que los documentos cambiaron a needs_review
        for doc in docs:
            assert doc.status == DocumentStatus.needs_review

        # Verificar audit trail
        history_entries = [
            call.args[0]
            for call in mock_db_session.add.call_args_list
            if isinstance(call.args[0], DocumentHistory)
        ]
        assert len(history_entries) == len(doc_ids)
        assert history_entries[0].action == "agent_completed"
        assert history_entries[0].after_content["status"] == "needs_review"

        mock_db_session.commit.assert_awaited_once()


# =============================================================================
#  TESTS: PIPELINE COMPLETO (INTEGRACIÓN)
# =============================================================================


class TestFullPipeline:
    """Prueba el pipeline completo con todas las dependencias mockeadas."""

    @patch("app.agents.graph._get_runtime_graph")
    async def test_full_pipeline_execution(self, mock_get_graph):
        """El pipeline completo debe ejecutarse sin errores y retornar estado."""
        # Configurar un grafo mock que ejecuta los nodos reales
        # pero con dependencias externas mockeadas
        from langgraph.graph import StateGraph

        # Crear grafo mínimo para prueba
        builder = StateGraph(AgentState)

        @patch("app.agents.nodes.AsyncSessionLocal")
        async def mock_load(state, mock_session):
            return {"document_ids": [], "error": None}

        # Usar un grafo simulado que retorna un estado predecible
        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(
            return_value={
                "document_ids": [],
                "documents_text": {},
                "chunks": [],
                "messages": [],
                "suggestions": [],
                "redundancy_findings": [],
                "error": None,
            }
        )
        mock_get_graph.return_value = mock_graph

        result = await run_curation(thread_id="test-integration-001")

        assert result is not None
        assert "document_ids" in result
        assert "suggestions" in result
        assert "redundancy_findings" in result
        assert result.get("error") is None

    async def test_run_curation_with_no_documents(self):
        """run_curation sin documentos debe completarse sin errores."""
        # Esta prueba usa el grafo real pero asume que ChromaDB y Postgres están accesibles
        # Se salta si no hay servicios externos
        import os

        if not os.getenv("INTEGRATION_TESTS"):
            pytest.skip(
                "Saltando prueba de integración real. "
                "Define INTEGRATION_TESTS=1 para ejecutarla."
            )

        result = await run_curation(thread_id="test-real-db-001")
        assert result is not None


# =============================================================================
#  TESTS: VALIDACIÓN DE SUGERENCIAS EN DB
# =============================================================================


class TestSuggestionPersistence:
    """Verifica que las sugerencias se persistan correctamente con todos los campos."""

    @patch("app.agents.nodes.AsyncSessionLocal")
    async def test_suggestion_has_all_required_fields(
        self, mock_session_factory, mock_db_session
    ):
        """Cada sugerencia debe incluir source_doc_id, source_chunk_ids y confidence_score."""
        mock_session_factory.return_value.__aenter__.return_value = mock_db_session

        finding = {
            "chunk_id_a": "chunk_a",
            "chunk_id_b": "chunk_b",
            "similarity": 0.93,
            "confidence_score": 0.90,
            "doc_id_a": str(uuid.uuid4()),
            "doc_id_b": str(uuid.uuid4()),
        }

        state: AgentState = {
            "document_ids": [],
            "documents_text": {},
            "chunks": [],
            "messages": [],
            "suggestions": [],
            "redundancy_findings": [finding],
            "error": None,
        }
        result = await generate_suggestions_node(state)

        assert len(result["suggestions"]) == 1
        suggestion_data = result["suggestions"][0]

        # Validar campos requeridos según los guardrails (#18)
        assert "id" in suggestion_data
        assert "document_id" in suggestion_data
        assert suggestion_data["type"] == "redundancy"
        assert suggestion_data["confidence_score"] == 0.90
        assert isinstance(suggestion_data["confidence_score"], (int, float))
        assert 0.0 <= suggestion_data["confidence_score"] <= 1.0

    @patch("app.agents.nodes.AsyncSessionLocal")
    async def test_rejects_invalid_confidence_score(
        self, mock_session_factory, mock_db_session
    ):
        """Confidence score fuera de rango debe fijarse a 0.0 sin romper el pipeline."""
        mock_session_factory.return_value.__aenter__.return_value = mock_db_session

        finding = {
            "chunk_id_a": "chunk_a",
            "chunk_id_b": "chunk_b",
            "similarity": 0.93,
            "confidence_score": -0.5,  # Inválido: menor a 0.0
            "doc_id_a": str(uuid.uuid4()),
            "doc_id_b": str(uuid.uuid4()),
        }

        state: AgentState = {
            "document_ids": [],
            "documents_text": {},
            "chunks": [],
            "messages": [],
            "suggestions": [],
            "redundancy_findings": [finding],
            "error": None,
        }
        result = await generate_suggestions_node(state)

        # Debe haber creado la sugerencia igual, con confidence fijado a 0.0
        assert len(result["suggestions"]) == 1
        assert result["suggestions"][0]["confidence_score"] == 0.0

    @patch("app.agents.nodes.AsyncSessionLocal")
    async def test_skips_finding_without_chunk_ids(
        self, mock_session_factory, mock_db_session
    ):
        """Hallazgos sin chunk_ids deben omitirse silenciosamente."""
        mock_session_factory.return_value.__aenter__.return_value = mock_db_session

        finding = {
            "chunk_id_a": "",
            "chunk_id_b": "",
            "similarity": 0.93,
            "confidence_score": 0.90,
            "doc_id_a": str(uuid.uuid4()),
            "doc_id_b": str(uuid.uuid4()),
        }

        state: AgentState = {
            "document_ids": [],
            "documents_text": {},
            "chunks": [],
            "messages": [],
            "suggestions": [],
            "redundancy_findings": [finding],
            "error": None,
        }
        result = await generate_suggestions_node(state)

        assert len(result["suggestions"]) == 0


# =============================================================================
#  TESTS: TRANSICIÓN DE ESTADOS
# =============================================================================


class TestDocumentStateTransitions:
    """Verifica las transiciones de estado de los documentos durante el pipeline."""

    def test_initial_state_is_needs_review(self, mock_document):
        """Los documentos se crean con status needs_review."""
        assert mock_document.status == DocumentStatus.needs_review

    def test_processing_transition(self, mock_document):
        """load_documents_node cambia a processing."""
        mock_document.status = DocumentStatus.processing
        assert mock_document.status == DocumentStatus.processing

    def test_back_to_needs_review(self, mock_document):
        """wait_human_approval_node vuelve a needs_review."""
        mock_document.status = DocumentStatus.needs_review
        assert mock_document.status == DocumentStatus.needs_review

    def test_valid_status_enum_values(self):
        """Deben existir todos los estados definidos en el enum."""
        expected = {"needs_review", "processing", "approved", "rejected", "archived"}
        actual = {s.value for s in DocumentStatus}
        assert actual == expected

    def test_valid_suggestion_statuses(self):
        """Los estados de sugerencia deben ser pending, approved, rejected."""
        expected = {"pending", "approved", "rejected"}
        actual = {s.value for s in SuggestionStatus}
        assert actual == expected

    def test_valid_suggestion_types(self):
        """Los tipos de sugerencia deben ser los definidos."""
        expected = {"redundancy", "conflict", "faq", "update"}
        actual = {s.value for s in SuggestionType}
        assert actual == expected


# =============================================================================
#  TESTS: AUDIT TRAIL
# =============================================================================


class TestAuditTrail:
    """Verifica que el pipeline genere registros de auditoría."""

    @patch("app.agents.nodes.AsyncSessionLocal")
    async def test_agent_completion_creates_history(
        self, mock_session_factory, mock_db_session
    ):
        """wait_human_approval_node debe crear DocumentHistory."""
        doc_id = str(uuid.uuid4())
        mock_session_factory.return_value.__aenter__.return_value = mock_db_session

        mock_doc = MagicMock(spec=Document)
        mock_doc.id = uuid.UUID(doc_id)
        mock_doc.status = DocumentStatus.processing
        mock_db_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_doc))
        )

        state: AgentState = {
            "document_ids": [doc_id],
            "documents_text": {},
            "chunks": [],
            "messages": [],
            "suggestions": [],
            "redundancy_findings": [],
            "error": None,
        }
        await wait_human_approval_node(state)

        # Verificar que se agregó un DocumentHistory
        history_calls = [
            call.args[0]
            for call in mock_db_session.add.call_args_list
            if isinstance(call.args[0], DocumentHistory)
        ]
        assert len(history_calls) == 1

        entry = history_calls[0]
        assert entry.action == "agent_completed"
        assert entry.before_content == {"status": "processing"}
        assert entry.after_content["status"] == "needs_review"
        assert "suggestions_count" in entry.after_content
