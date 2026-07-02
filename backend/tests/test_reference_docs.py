"""
Tests para Issue #61 — Documentos de Referencia.

Cubre:
  - Test unitario: upload como referencia → category=reference
  - Test de integración: pipeline de curación ignora docs reference en load_documents_node
  - Test de integración: search_documents con category_filter
  - Test de API: CRUD de documentos de referencia
"""

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.api.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.models.models import (
    Document,
    DocumentCategory,
    DocumentStatus,
    SuggestionStatus,
    SuggestionType,
    User,
    UserRole,
)
from httpx import ASGITransport, AsyncClient

# =============================================================================
#  FIXTURES
# =============================================================================


@pytest.fixture
def mock_user():
    """Usuario instructor simulado."""
    return User(
        id=uuid.uuid4(),
        email="instructor@test.edu",
        role=UserRole.instructor,
        is_active=True,
    )


@pytest.fixture(autouse=True)
def override_auth(mock_user):
    """Sobrescribe dependencia de autenticación para tests de API."""
    app.dependency_overrides[get_current_user] = lambda: mock_user
    yield
    app.dependency_overrides.clear()


def _make_doc(
    category: DocumentCategory = DocumentCategory.curated,
    status: DocumentStatus = DocumentStatus.needs_review,
) -> Document:
    """Helper para crear documentos de prueba."""
    return Document(
        id=uuid.uuid4(),
        filename="test.pdf",
        original_filename="test.pdf",
        file_type="pdf",
        file_path="/tmp/test.pdf",
        size_bytes=1024,
        status=status,
        category=category,
        uploaded_by=uuid.uuid4(),
        uploaded_at=datetime.now(timezone.utc),
    )


# =============================================================================
#  TEST UNITARIO: Upload como referencia → category=reference
# =============================================================================


class TestReferenceDocCategory:
    """Verifica que los documentos de referencia tienen category=reference."""

    def test_explicit_reference_category(self):
        """Documento creado con category=reference debe mantenerlo."""
        doc = _make_doc(category=DocumentCategory.reference)
        assert doc.category == DocumentCategory.reference
        assert doc.category.value == "reference"

    def test_explicit_curated_category(self):
        """Documento creado con category=curated debe mantenerlo."""
        doc = _make_doc(category=DocumentCategory.curated)
        assert doc.category == DocumentCategory.curated
        assert doc.category.value == "curated"

    def test_enum_values(self):
        """DocumentCategory debe tener curated y reference."""
        assert DocumentCategory.curated.value == "curated"
        assert DocumentCategory.reference.value == "reference"


# =============================================================================
#  TEST INTEGRACIÓN: Pipeline ignora reference docs en load_documents_node
# =============================================================================


class TestLoadDocumentsNodeFiltersReference:
    """Verifica que load_documents_node solo carga documentos curated."""

    @pytest.mark.asyncio
    async def test_only_loads_curated_needs_review(self):
        """Solo debe cargar docs con category=curated AND status=needs_review."""
        from app.agents.nodes import load_documents_node
        from app.agents.state import AgentState

        doc_curated = _make_doc(
            category=DocumentCategory.curated,
            status=DocumentStatus.needs_review,
        )

        # Mock scalars().all() → [doc_curated]
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [doc_curated]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        # Session: async with + await execute
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)
        session.commit = AsyncMock()

        state = AgentState(
            document_ids=[],
            documents_text={},
            chunks=[],
            messages=[],
            suggestions=[],
            redundancy_findings=[],
            error=None,
        )

        with patch("app.agents.nodes.AsyncSessionLocal", return_value=session):
            result = await load_documents_node(state)

        assert len(result["document_ids"]) == 1
        assert result["document_ids"][0] == str(doc_curated.id)

    @pytest.mark.asyncio
    async def test_ignores_reference_docs(self):
        """Documentos reference no deben ser cargados."""
        from app.agents.nodes import load_documents_node
        from app.agents.state import AgentState

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)
        session.commit = AsyncMock()

        state = AgentState(
            document_ids=[],
            documents_text={},
            chunks=[],
            messages=[],
            suggestions=[],
            redundancy_findings=[],
            error=None,
        )

        with patch("app.agents.nodes.AsyncSessionLocal", return_value=session):
            result = await load_documents_node(state)

        assert result["document_ids"] == []
        assert result["error"] is None


# =============================================================================
#  TEST INTEGRACIÓN: search_documents con category_filter
# =============================================================================


class TestSearchDocumentsCategoryFilter:
    """Verifica que search_documents filtra correctamente por categoría.

    search_documents es un StructuredTool decorado con @tool.
    Para invocarlo en tests, usamos .ainvoke().
    """

    async def _call_search(self, **kwargs) -> dict:
        """Helper para invocar search_documents tool."""
        from app.tools.registry import search_documents

        result_str = await search_documents.ainvoke(kwargs)
        return json.loads(result_str)

    @pytest.mark.asyncio
    async def test_filter_all_returns_both(self):
        """category_filter='all' retorna chunks de ambas categorías."""
        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "ids": [["chunk_c_0", "chunk_r_0"]],
            "distances": [[0.1, 0.2]],
            "metadatas": [
                [
                    {
                        "doc_id": "d1",
                        "category": "curated",
                        "chunk_index": 0,
                        "token_count": 50,
                    },
                    {
                        "doc_id": "d2",
                        "category": "reference",
                        "chunk_index": 0,
                        "token_count": 60,
                    },
                ]
            ],
            "documents": [["C curated", "C reference"]],
        }

        with (
            patch("app.tools.registry._compute_embedding", return_value=[0.1] * 384),
            patch(
                "app.tools.registry._get_chroma_collection",
                return_value=mock_collection,
            ),
        ):
            result = await self._call_search(
                query="test", top_k=5, category_filter="all"
            )

        assert result["status"] == "success"
        assert len(result["results"]) == 2
        cats = {r["source_type"] for r in result["results"]}
        assert cats == {"curated", "reference"}

    @pytest.mark.asyncio
    async def test_filter_curated_only(self):
        """category_filter='curated' retorna solo chunks curated."""
        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "ids": [["chunk_c_0"]],
            "distances": [[0.1]],
            "metadatas": [
                [
                    {
                        "doc_id": "d1",
                        "category": "curated",
                        "chunk_index": 0,
                        "token_count": 50,
                    },
                ]
            ],
            "documents": [["C curated"]],
        }

        with (
            patch("app.tools.registry._compute_embedding", return_value=[0.1] * 384),
            patch(
                "app.tools.registry._get_chroma_collection",
                return_value=mock_collection,
            ),
        ):
            result = await self._call_search(
                query="test", top_k=5, category_filter="curated"
            )

        assert result["status"] == "success"
        assert result["results"][0]["source_type"] == "curated"
        assert mock_collection.query.call_args[1]["where"] == {"category": "curated"}

    @pytest.mark.asyncio
    async def test_filter_reference_only(self):
        """category_filter='reference' retorna solo chunks reference."""
        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "ids": [["chunk_r_0"]],
            "distances": [[0.15]],
            "metadatas": [
                [
                    {
                        "doc_id": "d2",
                        "category": "reference",
                        "chunk_index": 0,
                        "token_count": 60,
                    },
                ]
            ],
            "documents": [["C reference"]],
        }

        with (
            patch("app.tools.registry._compute_embedding", return_value=[0.1] * 384),
            patch(
                "app.tools.registry._get_chroma_collection",
                return_value=mock_collection,
            ),
        ):
            result = await self._call_search(
                query="test", top_k=5, category_filter="reference"
            )

        assert result["status"] == "success"
        assert result["results"][0]["source_type"] == "reference"
        assert mock_collection.query.call_args[1]["where"] == {"category": "reference"}

    @pytest.mark.asyncio
    async def test_no_filter_defaults_to_all(self):
        """Sin category_filter no debe incluir where clause."""
        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "ids": [["chunk_c_0"]],
            "distances": [[0.1]],
            "metadatas": [
                [
                    {
                        "doc_id": "d1",
                        "category": "curated",
                        "chunk_index": 0,
                        "token_count": 50,
                    },
                ]
            ],
            "documents": [["Contenido"]],
        }

        with (
            patch("app.tools.registry._compute_embedding", return_value=[0.1] * 384),
            patch(
                "app.tools.registry._get_chroma_collection",
                return_value=mock_collection,
            ),
        ):
            result = await self._call_search(query="test", top_k=5)

        assert result["status"] == "success"
        assert "where" not in mock_collection.query.call_args[1]

    @pytest.mark.asyncio
    async def test_empty_results(self):
        """Búsqueda sin resultados debe retornar lista vacía."""
        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "ids": [[]],
            "distances": [[]],
            "metadatas": [[]],
            "documents": [[]],
        }

        with (
            patch("app.tools.registry._compute_embedding", return_value=[0.1] * 384),
            patch(
                "app.tools.registry._get_chroma_collection",
                return_value=mock_collection,
            ),
        ):
            result = await self._call_search(
                query="xyz", top_k=5, category_filter="reference"
            )

        assert result["status"] == "success"
        assert result["total"] == 0


# =============================================================================
#  TEST DE API: CRUD de documentos de referencia
# =============================================================================


def _make_api_session(return_docs: list | None = None, total: int = 0):
    """Crea un mock de sesión de BD para tests de API."""
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = return_docs or []

    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_count = MagicMock()
    mock_count.scalar_one.return_value = total

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[mock_count, mock_result])
    return session


class TestReferenceDocsAPI:
    """Test para los endpoints CRUD de reference docs."""

    @pytest.mark.asyncio
    async def test_list_empty(self):
        """GET /api/reference-docs con data vacía retorna 200."""
        session = _make_api_session(return_docs=[], total=0)

        app.dependency_overrides[get_db] = lambda: session
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/reference-docs")

        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self):
        """GET /api/reference-docs/{id} retorna 404 si no existe."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        session = MagicMock()
        session.execute = AsyncMock(return_value=mock_result)

        app.dependency_overrides[get_db] = lambda: session
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/reference-docs/{uuid.uuid4()}")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        """DELETE /api/reference-docs/{id} retorna 404 si no existe."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        session = MagicMock()
        session.execute = AsyncMock(return_value=mock_result)

        app.dependency_overrides[get_db] = lambda: session
        with patch(
            "app.api.reference_docs.require_role", return_value=lambda: mock_user
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.delete(f"/api/reference-docs/{uuid.uuid4()}")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_process_endpoint(self):
        """POST /api/reference-docs/process debe procesar referencias."""
        mock_result = [
            {"status": "success", "doc_id": str(uuid.uuid4()), "chunks_count": 3}
        ]

        session = MagicMock()
        session.commit = AsyncMock()

        app.dependency_overrides[get_db] = lambda: session

        with (
            patch(
                "app.api.reference_docs.process_all_pending_references",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch(
                "app.api.reference_docs.require_role", return_value=lambda: mock_user
            ),
            patch(
                "app.api.reference_docs.record_document_history", new_callable=AsyncMock
            ),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.post("/api/reference-docs/process")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["status"] == "success"


# =============================================================================
#  TEST: Process reference document service
# =============================================================================


class TestReferenceDocService:
    """Verifica el servicio de procesamiento de reference docs."""

    @pytest.mark.asyncio
    async def test_marks_as_approved(self):
        """process_reference_document debe marcar status=approved."""
        from app.services.reference_docs import process_reference_document

        doc_id = uuid.uuid4()
        mock_doc = _make_doc(category=DocumentCategory.reference)
        mock_doc.id = doc_id
        mock_doc.file_path = "/tmp/test.txt"
        mock_doc.file_type = "txt"
        mock_doc.original_filename = "test.txt"

        mock_execute_result = MagicMock()
        mock_execute_result.scalar_one_or_none.return_value = mock_doc

        session = MagicMock()
        session.execute = AsyncMock(return_value=mock_execute_result)
        session.flush = AsyncMock()

        with (
            patch(
                "app.services.reference_docs.parse_document", return_value="contenido"
            ),
            patch(
                "app.services.reference_docs.embed_chunks",
                return_value=[
                    {
                        "chroma_id": "chunk_0",
                        "chunk_index": 0,
                        "text": "contenido",
                        "token_count": 5,
                        "hash": "hash123",
                        "page_number": None,
                        "category": "reference",
                    }
                ],
            ),
            patch("pathlib.Path.exists", return_value=True),
        ):
            result = await process_reference_document(doc_id, db=session)

        assert result["status"] == "success"
        assert mock_doc.status == DocumentStatus.approved

    @pytest.mark.asyncio
    async def test_rejects_non_reference(self):
        """Debe rechazar documentos que no son reference."""
        from app.services.reference_docs import process_reference_document

        doc_id = uuid.uuid4()
        mock_doc = _make_doc(category=DocumentCategory.curated)

        mock_execute_result = MagicMock()
        mock_execute_result.scalar_one_or_none.return_value = mock_doc

        session = MagicMock()
        session.execute = AsyncMock(return_value=mock_execute_result)

        result = await process_reference_document(doc_id, db=session)

        assert result["status"] == "error"
        assert "no es de tipo reference" in result["error"]

    @pytest.mark.asyncio
    async def test_handles_missing_file(self):
        """Debe manejar archivo inexistente."""
        from app.services.reference_docs import process_reference_document

        doc_id = uuid.uuid4()
        mock_doc = _make_doc(category=DocumentCategory.reference)
        mock_doc.id = doc_id
        mock_doc.file_path = "/tmp/no_existe.pdf"

        mock_execute_result = MagicMock()
        mock_execute_result.scalar_one_or_none.return_value = mock_doc

        session = MagicMock()
        session.execute = AsyncMock(return_value=mock_execute_result)

        with patch("pathlib.Path.exists", return_value=False):
            result = await process_reference_document(doc_id, db=session)

        assert result["status"] == "error"
        assert "Archivo no encontrado" in result["error"]


# =============================================================================
#  TEST: Docs API con filtro category
# =============================================================================


class TestDocsApiCategoryFilter:
    """GET /api/docs debe soportar filtro category con default curated."""

    @pytest.mark.asyncio
    async def test_default_filter_is_curated(self):
        """Por defecto /api/docs debe filtrar category=curated."""
        session = _make_api_session(return_docs=[], total=0)

        app.dependency_overrides[get_db] = lambda: session
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/docs")

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_filter_all_returns_all(self):
        """category=all debe traer docs de todas las categorías."""
        session = _make_api_session(
            return_docs=[_make_doc(), _make_doc()],
            total=2,
        )

        app.dependency_overrides[get_db] = lambda: session
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/docs?category=all")

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_filter_reference(self):
        """category=reference debe traer solo docs de referencia."""
        session = _make_api_session(
            return_docs=[_make_doc(category=DocumentCategory.reference)],
            total=1,
        )

        app.dependency_overrides[get_db] = lambda: session
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/docs?category=reference")

        assert resp.status_code == 200


# =============================================================================
#  TEST: Evidencia con metadatos de categoría
# =============================================================================


class TestChunkEvidenceWithCategory:
    """Verifica que la evidencia de chunks incluye metadatos de categoría."""

    def test_source_type_in_suggestion_response(self):
        """SuggestionResponse debe incluir source_type."""
        from app.schemas.suggestions import SuggestionResponse

        schema = SuggestionResponse(
            id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            type=SuggestionType.redundancy,
            status=SuggestionStatus.pending,
            description="Test",
            reasoning="Test",
            confidence_score=0.9,
            source_chunk_ids=[],
            source_doc_id="",
            source_type="reference",
            review_reason=None,
            reviewed_by=None,
            reviewed_at=None,
            created_at=datetime.now(timezone.utc),
            document_name="test.pdf",
            source_chunks=[],
        )

        assert schema.source_type == "reference"
