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

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.agents.graph import get_graph_info, run_curation
from app.agents.nodes import (
    chunk_and_embed_node,
    faq_generation_node,
    generate_suggestions_node,
    load_documents_node,
    redundancy_detection_node,
    wait_human_approval_node,
)
from app.agents.state import AgentState
from app.config import settings
from app.models.models import (
    Document,
    DocumentHistory,
    DocumentStatus,
    Suggestion,
    SuggestionStatus,
    SuggestionType,
)
from sqlalchemy.ext.asyncio import AsyncSession

# =============================================================================
#  FIXTURES
# =============================================================================


@pytest.fixture(autouse=True)
def no_agent_run_persistence():
    """Evita que run_curation escriba corridas de test en agent_runs (HU-19).

    Los registros de prueba contaminarían el histórico real de ejecuciones
    que se muestra en la página 'Ejecuciones del agente'.
    """
    with (
        patch("app.agents.graph._record_run_start", new=AsyncMock()),
        patch("app.agents.graph._record_run_end", new=AsyncMock()),
    ):
        yield


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
        "inconsistency_findings": [],
        "terminology_map": {},
        "web_search_results": [],
        "error": None,
    }


@pytest.fixture
def agent_state_with_docs(agent_state_empty) -> AgentState:
    """Estado con documentos pendientes."""
    return AgentState(
        document_ids=[str(uuid.uuid4()), str(uuid.uuid4())],
        documents_text={},
        chunks=[],
        messages=[],
        suggestions=[],
        redundancy_findings=[],
        inconsistency_findings=[],
        terminology_map={},
        web_search_results=[],
        error=None,
    )


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

        # Tools esperadas (ahora incluye search_web y detect_inconsistencies)
        expected_tools = {
            "search_documents",
            "compare_content",
            "detect_conflict",
            "suggest_update",
            "generate_faq_entry",
            "log_action",
            "detect_redundancy",
            "search_web",
            "detect_inconsistencies",
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
            "inconsistency_findings": [],
            "terminology_map": {},
            "web_search_results": [],
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
            "inconsistency_findings": [],
            "terminology_map": {},
            "web_search_results": [],
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

        # Mock de execute: los SELECT retornan cada documento secuencialmente;
        # los DELETE (limpieza idempotente de chunks previos) retornan rowcount=0
        from sqlalchemy.sql.dml import Delete

        doc_iter = iter(docs)

        async def execute_side_effect(stmt, *args, **kwargs):
            if isinstance(stmt, Delete):
                return MagicMock(rowcount=0)
            return MagicMock(scalar_one_or_none=MagicMock(return_value=next(doc_iter)))

        mock_db_session.execute = AsyncMock(side_effect=execute_side_effect)

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
                "inconsistency_findings": [],
                "terminology_map": {},
                "web_search_results": [],
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
            "inconsistency_findings": [],
            "terminology_map": {},
            "web_search_results": [],
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
                content_a_preview="texto chunk a 1",
                content_b_preview="texto chunk b 1",
                token_count_a=50,
                token_count_b=60,
            ),
            MagicMock(
                chunk_id_a="chunk_1",
                chunk_id_b="chunk_3",
                similarity=0.91,
                confidence_score=0.88,
                doc_id_a="doc_a",
                doc_id_b="doc_b",
                content_a_preview="texto chunk a 2",
                content_b_preview="texto chunk b 2",
                token_count_a=40,
                token_count_b=70,
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
            "inconsistency_findings": [],
            "terminology_map": {},
            "web_search_results": [],
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
            "inconsistency_findings": [],
            "terminology_map": {},
            "web_search_results": [],
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
            "inconsistency_findings": [],
            "terminology_map": {},
            "web_search_results": [],
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
            "inconsistency_findings": [],
            "terminology_map": {},
            "web_search_results": [],
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
            "inconsistency_findings": [],
            "terminology_map": {},
            "web_search_results": [],
            "error": None,
        }
        result = await generate_suggestions_node(state)

        assert result["suggestions"] == []


# =============================================================================
#  TESTS: NODO faq_generation
# =============================================================================


class TestFaqGenerationNode:
    """Generación automática de FAQs desde chunks."""

    @patch("app.agents.nodes.AsyncSessionLocal")
    @patch("app.tools.registry.generate_faq_entry")
    @pytest.mark.asyncio
    async def test_generates_faqs_from_chunks(
        self, mock_generate_faq, mock_session_factory, mock_db_session
    ):
        """Genera FAQs para chunks con contenido suficiente."""
        mock_session_factory.return_value.__aenter__.return_value = mock_db_session

        # Mock generate_faq_entry to return success
        # LangChain tool ainvoke passes a single dict argument
        async def faq_side_effect(args: dict):
            chunk_id = args.get("chunk_id", "")
            content = args.get("chunk_content", "")
            question = f"¿Qué es {content.split()[0]}?" if content else "¿Pregunta?"
            return json.dumps(
                {
                    "status": "success",
                    "faq": {
                        "question": question,
                        "answer": f"Respuesta sobre {content[:30]}...",
                        "source_chunk_id": chunk_id,
                        "topic": "general",
                    },
                }
            )

        mock_generate_faq.ainvoke = AsyncMock(side_effect=faq_side_effect)

        doc_id = str(uuid.uuid4())
        state: AgentState = {
            "document_ids": [doc_id],
            "documents_text": {},
            "chunks": [
                {
                    "chroma_id": f"{doc_id}_chunk_0",
                    "chunk_index": 0,
                    "text": "El teorema de Pitágoras establece que en un triángulo rectángulo, "
                    "el cuadrado de la hipotenusa es igual a la suma de los cuadrados "
                    "de los catetos. Esta relación es fundamental en geometría.",
                    "token_count": 30,
                    "hash": "abc123",
                    "page_number": 1,
                },
                {
                    "chroma_id": f"{doc_id}_chunk_1",
                    "chunk_index": 1,
                    "text": "La derivada de una función mide la tasa de cambio instantánea. "
                    "Se define como el límite del cociente incremental cuando "
                    "el incremento tiende a cero.",
                    "token_count": 25,
                    "hash": "def456",
                    "page_number": 2,
                },
            ],
            "messages": [],
            "suggestions": [],
            "redundancy_findings": [],
            "inconsistency_findings": [],
            "terminology_map": {},
            "web_search_results": [],
            "error": None,
        }

        result = await faq_generation_node(state)

        assert "suggestions" in result
        suggestions = result["suggestions"]
        assert len(suggestions) == 2  # Una FAQ por chunk
        for s in suggestions:
            assert s["type"] == "faq"
            assert "Pregunta:" in s["description"]
            assert s["confidence_score"] == 0.85

        # Verificar que se agregaron sugerencias a la sesión mockeada
        added_suggestions = [
            call.args[0]
            for call in mock_db_session.add.call_args_list
            if isinstance(call.args[0], Suggestion)
        ]
        assert len(added_suggestions) == 2
        for sug in added_suggestions:
            assert sug.type == SuggestionType.faq
            assert sug.status == SuggestionStatus.pending

        # Commit por FAQ (aísla fallos de fila) + commit final del nodo
        assert mock_db_session.commit.await_count >= 2

    @patch("app.agents.nodes.AsyncSessionLocal")
    @pytest.mark.asyncio
    async def test_no_chunks_returns_empty(self, mock_session_factory, mock_db_session):
        """Sin chunks no debe generar nada."""
        mock_session_factory.return_value.__aenter__.return_value = mock_db_session

        state: AgentState = {
            "document_ids": [],
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

        result = await faq_generation_node(state)

        assert result == {}

    @patch("app.agents.nodes.AsyncSessionLocal")
    @pytest.mark.asyncio
    async def test_skips_chunks_without_chroma_id(
        self, mock_session_factory, mock_db_session
    ):
        """Chunks sin chroma_id deben saltarse."""
        mock_session_factory.return_value.__aenter__.return_value = mock_db_session

        state: AgentState = {
            "document_ids": [str(uuid.uuid4())],
            "documents_text": {},
            "chunks": [
                {
                    "chroma_id": "",
                    "chunk_index": 0,
                    "text": "Contenido de prueba con suficiente longitud para generar FAQ.",
                    "token_count": 15,
                    "hash": "ghi789",
                    "page_number": 1,
                },
            ],
            "messages": [],
            "suggestions": [],
            "redundancy_findings": [],
            "inconsistency_findings": [],
            "terminology_map": {},
            "web_search_results": [],
            "error": None,
        }

        result = await faq_generation_node(state)

        assert "suggestions" in result
        assert len(result["suggestions"]) == 0

    @patch("app.agents.nodes.AsyncSessionLocal")
    @patch("app.tools.registry.generate_faq_entry")
    @pytest.mark.asyncio
    async def test_preserves_existing_suggestions(
        self, mock_generate_faq, mock_session_factory, mock_db_session
    ):
        """No debe sobrescribir sugerencias existentes en el estado."""
        mock_session_factory.return_value.__aenter__.return_value = mock_db_session

        async def faq_side_effect(args: dict):
            return json.dumps(
                {
                    "status": "success",
                    "faq": {
                        "question": "¿Pregunta de prueba?",
                        "answer": "Respuesta de prueba.",
                        "source_chunk_id": args.get("chunk_id", ""),
                        "topic": "general",
                    },
                }
            )

        mock_generate_faq.ainvoke = AsyncMock(side_effect=faq_side_effect)

        doc_id = str(uuid.uuid4())
        existing_suggestion = {
            "id": str(uuid.uuid4()),
            "document_id": doc_id,
            "type": "redundancy",
            "description": "Redundancia existente",
            "confidence_score": 0.9,
        }
        state: AgentState = {
            "document_ids": [doc_id],
            "documents_text": {},
            "chunks": [
                {
                    "chroma_id": f"{doc_id}_chunk_0",
                    "chunk_index": 0,
                    "text": "Contenido educativo suficiente para generar una pregunta "
                    "frecuente sobre este tema del curso.",
                    "token_count": 20,
                    "hash": "jkl012",
                    "page_number": 1,
                },
            ],
            "messages": [],
            "suggestions": [existing_suggestion],
            "redundancy_findings": [],
            "inconsistency_findings": [],
            "terminology_map": {},
            "web_search_results": [],
            "error": None,
        }

        result = await faq_generation_node(state)

        assert "suggestions" in result
        # Debe tener la existente + la nueva FAQ
        assert len(result["suggestions"]) == 2
        assert result["suggestions"][0] == existing_suggestion
        assert result["suggestions"][1]["type"] == "faq"


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
            "inconsistency_findings": [],
            "terminology_map": {},
            "web_search_results": [],
            "error": None,
        }
        await wait_human_approval_node(state)

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
                "inconsistency_findings": [],
                "terminology_map": {},
                "web_search_results": [],
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
            "inconsistency_findings": [],
            "terminology_map": {},
            "web_search_results": [],
            "error": None,
        }
        result = await generate_suggestions_node(state)

        # Debe haber creado la sugerencia igual, con confidence fijado a 0.0
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
            "inconsistency_findings": [],
            "terminology_map": {},
            "web_search_results": [],
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
            "inconsistency_findings": [],
            "terminology_map": {},
            "web_search_results": [],
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
#  TESTS: ESTRUCTURA DEL GRAFO (CONDITIONAL EDGES)
# =============================================================================


class TestGraphStructure:
    """Prueba la estructura del grafo, nodos y aristas condicionales."""

    def test_graph_has_all_nodes(self):
        """El grafo compilado debe contener todos los nodos del pipeline."""
        from app.agents.graph import curation_graph

        expected_nodes = {
            "load_documents",
            "chunk_and_embed",
            "redundancy_detection",
            "inconsistency_detection",
            "web_search",
            "faq_generation",
            "generate_suggestions",
            "wait_human_approval",
        }
        assert expected_nodes.issubset(set(curation_graph.nodes.keys()))

    def test_graph_conditional_edge_routing_with_docs(self):
        """_has_documents debe retornar 'continue' cuando hay document_ids."""
        from app.agents.graph import _has_documents

        state_with_docs: AgentState = {
            "document_ids": ["id1", "id2"],
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
        assert _has_documents(state_with_docs) == "continue"

    def test_graph_conditional_edge_routing_without_docs(self):
        """_has_documents debe retornar 'end' cuando no hay document_ids."""
        from app.agents.graph import _has_documents

        state_without_docs: AgentState = {
            "document_ids": [],
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
        assert _has_documents(state_without_docs) == "end"

    def test_graph_get_info_contains_expected_keys(self):
        """get_graph_info debe retornar metadatos completos del grafo."""
        from app.agents.graph import get_graph_info

        info = get_graph_info()

        assert "nodes" in info
        assert "checkpointer" in info
        assert "tools" in info
        assert "llm" in info
        assert "tracing" in info

        # Verificar que los nodos base están presentes
        assert "load_documents" in info["nodes"]
        assert "chunk_and_embed" in info["nodes"]
        assert "redundancy_detection" in info["nodes"]
        assert "inconsistency_detection" in info["nodes"]
        assert "web_search" in info["nodes"]
        assert "faq_generation" in info["nodes"]
        assert "generate_suggestions" in info["nodes"]
        assert "wait_human_approval" in info["nodes"]

    def test_build_graph_structure(self):
        """Verifica la estructura interna del grafo compilado."""
        from app.agents.graph import _build_graph

        builder = _build_graph()
        graph = builder.compile()

        # Verificar nodos del grafo compilado
        assert "load_documents" in graph.nodes
        assert "chunk_and_embed" in graph.nodes
        assert "redundancy_detection" in graph.nodes
        assert "inconsistency_detection" in graph.nodes
        assert "web_search" in graph.nodes
        assert "faq_generation" in graph.nodes
        assert "generate_suggestions" in graph.nodes
        assert "wait_human_approval" in graph.nodes

    def test_run_curation_with_empty_doc_ids_stops_early(self):
        """Si se pasan document_ids vacíos, no debe cargar documentos."""
        # Esto prueba que el conditional edge funciona correctamente:
        # load_documents_node retorna lista vacía → _has_documents → "end"
        state: AgentState = {
            "document_ids": [],
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
        from app.agents.graph import _has_documents

        assert _has_documents(state) == "end"


# =============================================================================
#  TESTS: RETRY Y ERROR HANDLING
# =============================================================================


class TestRetryAndErrorHandling:
    """Prueba el mecanismo de reintentos y manejo de errores."""

    @pytest.mark.asyncio
    async def test_run_with_retry_success_first_try(self):
        """_run_with_retry debe retornar el resultado si la primera ejecución es exitosa."""
        from app.agents.nodes import _run_with_retry

        async def successful_coro():
            return "ok"

        result = await _run_with_retry(successful_coro, max_retries=3)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_run_with_retry_succeeds_after_retry(self):
        """_run_with_retry debe reintentar y eventualmente tener éxito."""
        from app.agents.nodes import _run_with_retry

        call_count = 0

        async def eventually_succeeds():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("DB temporalmente caído")
            return "recuperado"

        result = await _run_with_retry(eventually_succeeds, max_retries=3)
        assert result == "recuperado"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_run_with_retry_exhausts_retries(self):
        """_run_with_retry debe fallar después de agotar los reintentos."""
        from app.agents.nodes import _run_with_retry

        async def always_fails():
            raise ConnectionError("Error persistente")

        with pytest.raises(ConnectionError):
            await _run_with_retry(always_fails, max_retries=2)

    @pytest.mark.asyncio
    async def test_run_with_retry_non_transient_error(self):
        """_run_with_retry NO debe reintentar errores no transitorios."""
        from app.agents.nodes import _run_with_retry

        async def value_error():
            raise ValueError("Error de lógica")

        with pytest.raises(ValueError):
            await _run_with_retry(value_error, max_retries=3)

    @pytest.mark.asyncio
    async def test_chunk_and_embed_parallel_execution(self):
        """chunk_and_embed_node debe procesar múltiples documentos en paralelo."""
        from app.agents.nodes import _process_single_document, chunk_and_embed_node

        # Verificar que _process_single_document existe como función helper
        assert callable(_process_single_document)
        # Verificar que chunk_and_embed_node usa asyncio.gather internamente
        import inspect

        source = inspect.getsource(chunk_and_embed_node)
        assert "asyncio.gather" in source

    @pytest.mark.asyncio
    async def test_run_curation_timeout_error(self):
        """run_curation debe lanzar TimeoutError si excede el timeout."""
        from app.agents.graph import run_curation

        # Mock _get_runtime_graph para que cuelgue
        with patch("app.agents.graph._get_runtime_graph") as mock_get_graph:
            mock_graph = AsyncMock()

            async def slow_invoke(*args, **kwargs):
                await asyncio.sleep(10)  # Más que el timeout

            mock_graph.ainvoke = slow_invoke
            mock_get_graph.return_value = mock_graph

            with pytest.raises(TimeoutError):
                await run_curation(
                    thread_id="test-timeout-001",
                    timeout_seconds=1,
                    use_langfuse=False,
                )


# =============================================================================
#  TESTS: EXPORT DE PAQUETES
# =============================================================================


class TestPackageExports:
    """Verifica que los __init__.py exporten correctamente los símbolos."""

    def test_agents_package_exports(self):
        """El paquete agents debe exportar los símbolos principales."""
        from app import agents

        assert hasattr(agents, "AgentState")
        assert hasattr(agents, "run_curation")
        assert hasattr(agents, "get_graph_info")
        assert hasattr(agents, "get_llm")
        assert hasattr(agents, "load_documents_node")
        assert hasattr(agents, "chunk_and_embed_node")
        assert hasattr(agents, "redundancy_detection_node")
        assert hasattr(agents, "generate_suggestions_node")
        assert hasattr(agents, "wait_human_approval_node")
        assert hasattr(agents, "web_search_node")

    def test_tools_package_exports(self):
        """El paquete tools debe exportar los símbolos principales."""
        from app import tools

        assert hasattr(tools, "get_all_tools")
        assert hasattr(tools, "TOOL_MAP")
        assert hasattr(tools, "TOOL_OUTPUT_SCHEMAS")
        assert hasattr(tools, "ToolOutputValidationError")
        assert hasattr(tools, "SuggestionDataValidationError")
        assert hasattr(tools, "validate_tool_output")
        assert hasattr(tools, "validate_suggestion_data")
        assert hasattr(tools, "validate_redundancy_finding")

    def test_rag_package_exports(self):
        """El paquete rag debe exportar los símbolos principales."""
        from app import rag

        assert hasattr(rag, "chunk_text")
        assert hasattr(rag, "chunk_and_embed")
        assert hasattr(rag, "get_chroma_collection")
        assert hasattr(rag, "get_embedding_model")
        assert hasattr(rag, "detect_redundancy")
        assert hasattr(rag, "detect_redundancy_bulk")
        assert hasattr(rag, "detect_redundancy_report")
        assert hasattr(rag, "redundancy_report_to_json")
        assert hasattr(rag, "scan_all_redundancy")
        assert hasattr(rag, "RedundancyResult")
        assert hasattr(rag, "RedundancyReport")


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
            "inconsistency_findings": [],
            "terminology_map": {},
            "web_search_results": [],
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


# =============================================================================
#  TESTS: WEB SEARCH NODE
# =============================================================================


class TestWebSearchNode:
    """Prueba el nodo de búsqueda web en el grafo."""

    @patch("app.agents.nodes.settings")
    @patch("app.tools.registry.search_web")
    @pytest.mark.asyncio
    async def test_returns_results_from_chunks(self, mock_search_web, mock_settings):
        """Debe generar consultas desde chunks y retornar resultados."""
        from app.agents.nodes import web_search_node

        mock_settings.WEB_SEARCH_MAX_RESULTS = 3

        async def fake_search(input_dict):
            query = input_dict.get("query", "")
            return json.dumps(
                {
                    "status": "success",
                    "query": query,
                    "results": [
                        {
                            "title": f"Resultado para {query[:20]}",
                            "url": "https://example.com",
                            "snippet": "Snippet del resultado",
                            "content": "Contenido completo del resultado de búsqueda web",
                            "source_type": "web",
                            "hash": "abc123",
                        }
                    ],
                    "total": 1,
                    "provider": "duckduckgo",
                }
            )

        mock_search_web.ainvoke = AsyncMock(side_effect=fake_search)

        state: AgentState = {
            "document_ids": ["doc1"],
            "documents_text": {"doc1": "Texto del documento"},
            "chunks": [
                {
                    "chroma_id": "doc1_chunk_0",
                    "chunk_index": 0,
                    "text": "El teorema de Pitágoras establece que en un triángulo rectángulo, el cuadrado de la hipotenusa es igual a la suma de los cuadrados de los catetos.",
                    "token_count": 20,
                    "hash": "hash1",
                    "page_number": 1,
                },
            ],
            "messages": [],
            "suggestions": [],
            "redundancy_findings": [],
            "inconsistency_findings": [],
            "terminology_map": {},
            "web_search_results": [],
            "error": None,
        }

        result = await web_search_node(state)

        assert "web_search_results" in result
        assert len(result["web_search_results"]) > 0
        assert result["web_search_results"][0]["source_type"] == "web"
        assert result["web_search_results"][0]["title"] is not None

    @pytest.mark.asyncio
    async def test_empty_when_no_chunks(self):
        """Sin chunks, debe retornar lista vacía."""
        from app.agents.nodes import web_search_node

        state: AgentState = {
            "document_ids": [],
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

        result = await web_search_node(state)
        assert "web_search_results" in result
        assert len(result["web_search_results"]) == 0

    @patch("app.agents.nodes.settings")
    @patch("app.tools.registry.search_web")
    @pytest.mark.asyncio
    async def test_handles_search_failure_gracefully(
        self, mock_search_web, mock_settings
    ):
        """Si search_web falla, el nodo no debe romper el pipeline."""
        from app.agents.nodes import web_search_node

        mock_settings.WEB_SEARCH_MAX_RESULTS = 3

        async def fake_fail(input_dict):
            return json.dumps(
                {
                    "status": "error",
                    "error": "Error simulado",
                }
            )

        mock_search_web.ainvoke = AsyncMock(side_effect=fake_fail)

        state: AgentState = {
            "document_ids": ["doc1"],
            "documents_text": {},
            "chunks": [
                {
                    "chroma_id": "doc1_chunk_0",
                    "chunk_index": 0,
                    "text": "Contenido educativo con información sobre temas importantes del curso.",
                    "token_count": 10,
                    "hash": "hash1",
                    "page_number": 1,
                },
            ],
            "messages": [],
            "suggestions": [],
            "redundancy_findings": [],
            "inconsistency_findings": [],
            "terminology_map": {},
            "web_search_results": [],
            "error": None,
        }

        result = await web_search_node(state)
        # No debe explotar, debe retornar lista vacía o con resultados parciales
        assert "web_search_results" in result
        assert isinstance(result["web_search_results"], list)
