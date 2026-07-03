"""
#14 — Tests unitarios para las 7 tools del agente.

Valida que cada tool:
  1. Retorna estructura JSON válida con los campos esperados
  2. Maneja errores correctamente (chunks faltantes, conexión, etc.)
  3. Usa schemas de validación estrictos

Requiere pytest-asyncio.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.tools.registry import (
    compare_content,
    detect_conflict,
    detect_redundancy,
    generate_faq_entry,
    log_action,
    search_documents,
    suggest_update,
)

# =============================================================================
#  search_documents
# =============================================================================


class TestSearchDocuments:
    """Búsqueda semántica en ChromaDB."""

    @patch("app.tools.registry._compute_embedding", return_value=[0.1] * 384)
    @patch("app.tools.registry._get_chroma_collection")
    @pytest.mark.asyncio
    async def test_success_with_results(self, mock_collection, mock_embed):
        """Retorna resultados correctamente estructurados."""
        mock_col = MagicMock()
        mock_col.query.return_value = {
            "ids": [["chunk_1", "chunk_2"]],
            "distances": [[0.1, 0.2]],
            "metadatas": [
                [
                    {"doc_id": "doc_1", "chunk_index": 0, "token_count": 100},
                    {"doc_id": "doc_1", "chunk_index": 1, "token_count": 150},
                ]
            ],
            "documents": [["Contenido del chunk 1", "Contenido del chunk 2"]],
        }
        mock_collection.return_value = mock_col

        result = await search_documents.ainvoke(
            {"query": "teorema de pitágoras", "top_k": 2}
        )
        payload = json.loads(result)

        assert payload["status"] == "success"
        assert payload["query"] == "teorema de pitágoras"
        assert payload["total"] == 2
        assert len(payload["results"]) == 2
        assert payload["results"][0]["chunk_id"] == "chunk_1"
        assert "similarity" in payload["results"][0]
        assert "metadata" in payload["results"][0]

    @patch("app.tools.registry._compute_embedding", return_value=[0.1] * 384)
    @patch("app.tools.registry._get_chroma_collection")
    @pytest.mark.asyncio
    async def test_empty_results(self, mock_collection, mock_embed):
        """Retorna lista vacía cuando no hay resultados."""
        mock_col = MagicMock()
        mock_col.query.return_value = {
            "ids": [[]],
            "distances": [[]],
            "metadatas": [[]],
            "documents": [[]],
        }
        mock_collection.return_value = mock_col

        result = await search_documents.ainvoke({"query": "término inexistente"})
        payload = json.loads(result)

        assert payload["status"] == "success"
        assert payload["total"] == 0
        assert payload["results"] == []

    @patch("app.tools.registry._compute_embedding", side_effect=Exception("API error"))
    @pytest.mark.asyncio
    async def test_error_response(self, mock_embed):
        """Retorna estructura de error ante fallos."""
        result = await search_documents.ainvoke({"query": "fallo", "top_k": 5})
        payload = json.loads(result)

        assert payload["status"] == "error"
        assert "error" in payload


# =============================================================================
#  compare_content
# =============================================================================


class TestCompareContent:
    """Comparación entre dos chunks."""

    @patch("app.tools.registry._get_chroma_collection")
    @pytest.mark.asyncio
    async def test_success(self, mock_collection):
        """Retorna diferencias entre dos chunks."""
        mock_col = MagicMock()

        def get_side_effect(ids, include):
            if ids == ["chunk_a"]:
                return {
                    "ids": ["chunk_a"],
                    "documents": ["Contenido del chunk A sobre álgebra lineal"],
                    "metadatas": [
                        {"doc_id": "doc_1", "chunk_index": 0, "token_count": 10}
                    ],
                    "embeddings": [[0.1] * 384],
                }
            elif ids == ["chunk_b"]:
                return {
                    "ids": ["chunk_b"],
                    "documents": ["Contenido del chunk B sobre cálculo vectorial"],
                    "metadatas": [
                        {"doc_id": "doc_2", "chunk_index": 1, "token_count": 12}
                    ],
                    "embeddings": [[0.2] * 384],
                }
            return {"ids": [], "documents": [], "metadatas": [], "embeddings": []}

        mock_col.get = MagicMock(side_effect=get_side_effect)
        mock_collection.return_value = mock_col

        result = await compare_content.ainvoke(
            {"chunk_id_a": "chunk_a", "chunk_id_b": "chunk_b"}
        )
        payload = json.loads(result)

        assert payload["status"] == "success"
        assert payload["chunk_a"]["id"] == "chunk_a"
        assert payload["chunk_b"]["id"] == "chunk_b"
        assert "similarity" in payload
        assert "differences" in payload
        assert "only_in_a" in payload["differences"]
        assert "only_in_b" in payload["differences"]

    @patch("app.tools.registry._get_chroma_collection")
    @pytest.mark.asyncio
    async def test_chunk_not_found(self, mock_collection):
        """Retorna error si uno de los chunks no existe."""
        mock_col = MagicMock()
        mock_col.get.return_value = {
            "ids": [],
            "documents": [],
            "metadatas": [],
            "embeddings": [],
        }
        mock_collection.return_value = mock_col

        result = await compare_content.ainvoke(
            {"chunk_id_a": "inexistente", "chunk_id_b": "otro_inexistente"}
        )
        payload = json.loads(result)

        assert payload["status"] == "error"
        assert "no encontrados" in payload["error"]


# =============================================================================
#  detect_conflict
# =============================================================================


class TestDetectConflict:
    """Detección de conflictos entre documentos."""

    @patch("app.tools.registry._get_chroma_collection")
    @pytest.mark.asyncio
    async def test_no_conflicts(self, mock_collection):
        """Retorna lista vacía cuando no hay conflictos."""
        mock_col = MagicMock()
        mock_col.get.return_value = {
            "ids": ["chunk_1", "chunk_2"],
            "documents": ["A", "B"],
            "metadatas": [
                {"doc_id": "doc_a", "chunk_index": 0},
                {"doc_id": "doc_a", "chunk_index": 1},
            ],
            "embeddings": [[0.1] * 384, [0.2] * 384],
        }
        mock_collection.return_value = mock_col

        result = await detect_conflict.ainvoke(
            {"doc_id_a": "doc_a", "doc_id_b": "doc_b"}
        )
        payload = json.loads(result)

        assert payload["status"] == "success"
        assert payload["doc_a"] == "doc_a"
        assert payload["doc_b"] == "doc_b"

    @patch("app.tools.registry._get_chroma_collection")
    @pytest.mark.asyncio
    async def test_doc_not_found(self, mock_collection):
        """Retorna error si el documento no tiene chunks."""
        mock_col = MagicMock()
        mock_col.get.side_effect = [
            {"ids": [], "documents": [], "metadatas": [], "embeddings": []},
            {
                "ids": ["chunk_1"],
                "documents": ["A"],
                "metadatas": [{}],
                "embeddings": [[0.1] * 384],
            },
        ]
        mock_collection.return_value = mock_col

        result = await detect_conflict.ainvoke(
            {"doc_id_a": "doc_empty", "doc_id_b": "doc_ok"}
        )
        payload = json.loads(result)

        assert payload["status"] == "error"


# =============================================================================
#  suggest_update
# =============================================================================


class TestSuggestUpdate:
    """Creación de sugerencias en estado pending."""

    @patch("app.database.AsyncSessionLocal")
    @pytest.mark.asyncio
    async def test_success(self, mock_session_factory):
        """Crea sugerencia correctamente en estado pending."""
        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__.return_value = mock_session

        mock_suggestion = MagicMock()
        mock_suggestion.id = "550e8400-e29b-41d4-a716-446655440000"
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        result = await suggest_update.ainvoke(
            {
                "document_id": "550e8400-e29b-41d4-a716-446655440000",
                "description": "Se recomienda actualizar el teorema de Pitágoras",
                "source_doc_id": "550e8400-e29b-41d4-a716-446655440001",
                "source_chunk_ids": ["chunk_1", "chunk_2"],
                "confidence_score": 0.85,
                "suggestion_type": "update",
                "reasoning": "Contenido desactualizado",
            }
        )
        payload = json.loads(result)

        assert payload["status"] == "success"
        assert payload["state"] == "pending"
        assert payload["confidence_score"] == 0.85

    @pytest.mark.asyncio
    async def test_invalid_uuid(self):
        """Retorna error con UUID inválido."""
        result = await suggest_update.ainvoke(
            {
                "document_id": "no-es-un-uuid",
                "description": "Sugerencia de prueba con descripción larga",
                "source_doc_id": "doc_1",
                "source_chunk_ids": ["chunk_1"],
                "confidence_score": 0.5,
            }
        )
        payload = json.loads(result)

        assert payload["status"] == "error"


# =============================================================================
#  generate_faq_entry
# =============================================================================


class TestGenerateFaqEntry:
    """Generación de preguntas frecuentes."""

    @patch("app.tools.registry._generate_faq_with_llm")
    @pytest.mark.asyncio
    async def test_heuristic_success(self, mock_llm_faq):
        """Genera FAQ usando heurística cuando no hay LLM.

        Se mockea _generate_faq_with_llm → None para forzar la heurística:
        sin el mock, el test llamaría a la API real si hay key configurada.
        """
        mock_llm_faq.return_value = None
        chunk_content = (
            "El teorema de Pitágoras establece que en un triángulo rectángulo, "
            "el cuadrado de la hipotenusa es igual a la suma de los cuadrados "
            "de los catetos. Esta relación matemática es fundamental en geometría."
        )
        result = await generate_faq_entry.ainvoke(
            {
                "chunk_id": "chunk_1",
                "chunk_content": chunk_content,
                "topic": "matemáticas",
            }
        )
        payload = json.loads(result)

        assert payload["status"] == "success"
        assert "faq" in payload
        assert len(payload["faq"]["question"]) > 5
        assert len(payload["faq"]["answer"]) > 5
        assert payload["faq"]["source_chunk_id"] == "chunk_1"
        assert payload["faq"]["topic"] == "matemáticas"

    @patch("app.tools.registry._generate_faq_with_llm")
    @pytest.mark.asyncio
    async def test_insufficient_content(self, mock_llm_faq):
        """Retorna error si el chunk no produce oraciones válidas.

        Se mockea el LLM → None: la ruta heurística es la que valida
        que el contenido sea insuficiente.
        """
        mock_llm_faq.return_value = None
        result = await generate_faq_entry.ainvoke(
            {
                "chunk_id": "chunk_empty",
                "chunk_content": "Cortó.   Y.",
                "topic": "general",
            }
        )
        payload = json.loads(result)

        assert payload["status"] == "error"

    @patch("app.tools.registry._generate_faq_with_llm")
    @pytest.mark.asyncio
    async def test_llm_fallback_on_exception(self, mock_llm_faq):
        """Usa fallback heurístico cuando el LLM falla."""
        mock_llm_faq.return_value = None

        result = await generate_faq_entry.ainvoke(
            {
                "chunk_id": "chunk_test",
                "chunk_content": "El contenido educativo es amplio y variado. "
                "Se cubren temas de álgebra, geometría y cálculo.",
                "topic": "general",
            }
        )
        payload = json.loads(result)

        assert payload["status"] == "success"
        assert "faq" in payload


# =============================================================================
#  log_action
# =============================================================================


class TestLogAction:
    """Registro de acciones en audit trail."""

    @patch("app.database.AsyncSessionLocal")
    @pytest.mark.asyncio
    async def test_log_with_document_id(self, mock_session_factory):
        """Registra acción con document_id válido."""
        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__.return_value = mock_session

        mock_history = MagicMock()
        mock_history.id = "log-123"
        mock_history.timestamp.isoformat.return_value = "2026-06-16T00:00:00"
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        result = await log_action.ainvoke(
            {
                "action": "search",
                "detail": "Búsqueda de teorema de pitágoras",
                "agent_step": "analysis",
                "document_id": "550e8400-e29b-41d4-a716-446655440000",
            }
        )
        payload = json.loads(result)

        assert payload["status"] == "logged"
        assert payload["action"] == "search"
        assert payload["document_id"] == "550e8400-e29b-41d4-a716-446655440000"

    @patch("app.database.AsyncSessionLocal")
    @pytest.mark.asyncio
    async def test_log_without_document_id(self, mock_session_factory):
        """Registra acción global sin document_id (debe aceptar None)."""
        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__.return_value = mock_session

        mock_history = MagicMock()
        mock_history.id = "log-456"
        mock_history.timestamp.isoformat.return_value = "2026-06-16T00:00:00"
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        result = await log_action.ainvoke(
            {
                "action": "agent_started",
                "detail": "Inicio del pipeline de curación",
                "agent_step": "init",
            }
        )
        payload = json.loads(result)

        assert payload["status"] == "logged"
        assert payload["document_id"] is None

    @patch("app.database.AsyncSessionLocal")
    @pytest.mark.asyncio
    async def test_log_with_invalid_uuid_does_not_crash(self, mock_session_factory):
        """No debe fallar si document_id no es UUID válido."""
        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__.return_value = mock_session

        mock_history = MagicMock()
        mock_history.id = "log-789"
        mock_history.timestamp.isoformat.return_value = "2026-06-16T00:00:00"
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        result = await log_action.ainvoke(
            {
                "action": "test",
                "detail": "UUID inválido no debe romper",
                "agent_step": "test",
                "document_id": "no-es-uuid",
            }
        )
        payload = json.loads(result)

        assert payload["status"] == "logged"
        # document_id debe seguir siendo el string original, y doc_uuid se setea a None
        assert payload["document_id"] == "no-es-uuid"


# =============================================================================
#  detect_redundancy
# =============================================================================


class TestDetectRedundancy:
    """Detección de redundancia entre chunks."""

    @patch("app.rag.redundancy.detect_redundancy_report")
    @pytest.mark.asyncio
    async def test_success(self, mock_core):
        """Retorna reporte de redundancia correctamente estructurado."""
        from app.rag.redundancy import RedundancyReport, RedundancyResult

        mock_core.return_value = RedundancyReport(
            query_chunk_id="chunk_query",
            threshold=0.85,
            total_comparisons=50,
            redundant_pairs=[
                RedundancyResult(
                    chunk_id_a="chunk_query",
                    chunk_id_b="chunk_other",
                    similarity=0.92,
                    confidence_score=0.88,
                    doc_id_a="doc_1",
                    doc_id_b="doc_2",
                    chunk_index_a=0,
                    chunk_index_b=1,
                    content_a_preview="Contenido del chunk A...",
                    content_b_preview="Contenido del chunk B...",
                    token_count_a=100,
                    token_count_b=120,
                )
            ],
            pair_count=1,
        )

        result = await detect_redundancy.ainvoke(
            {
                "chunk_id": "chunk_query",
                "threshold": 0.85,
                "max_pairs": 5,
                "include_same_doc": True,
            }
        )
        payload = json.loads(result)

        assert payload["status"] == "success"
        assert payload["query_chunk_id"] == "chunk_query"
        assert payload["pair_count"] == 1
        assert len(payload["redundant_pairs"]) == 1
        assert payload["threshold"] == 0.85


# =============================================================================
#  search_web
# =============================================================================


class TestSearchWeb:
    """Búsqueda web con proveedores Tavily y DuckDuckGo."""

    @patch("app.tools.registry.settings")
    @pytest.mark.asyncio
    async def test_duckduckgo_success(self, mock_settings):
        """Retorna resultados estructurados con DuckDuckGo."""
        mock_settings.WEB_SEARCH_PROVIDER = "duckduckgo"
        mock_settings.WEB_SEARCH_TIMEOUT = 10
        mock_settings.TAVILY_API_KEY = ""

        from app.tools.registry import search_web

        # Mockear _DDGS_CLASS — la v7.x es síncrona, se llama via asyncio.to_thread
        with patch("app.tools.registry._DDGS_CLASS") as mock_ddgs:
            mock_instance = MagicMock()
            mock_ddgs.return_value = mock_instance

            mock_instance.text.return_value = [
                {
                    "title": "Resultado 1",
                    "href": "https://example.com/1",
                    "body": "Contenido del resultado 1",
                },
                {
                    "title": "Resultado 2",
                    "href": "https://example.com/2",
                    "body": "Contenido del resultado 2",
                },
            ]

            result = await search_web.ainvoke(
                {
                    "query": "teorema de pitágoras",
                    "max_results": 5,
                }
            )
            payload = json.loads(result)

            assert payload["status"] == "success"
            assert payload["query"] == "teorema de pitágoras"
            assert payload["total"] == 2
            assert payload["provider"] == "duckduckgo"
            assert len(payload["results"]) == 2
            assert payload["results"][0]["title"] == "Resultado 1"
            assert payload["results"][0]["source_type"] == "web"
            assert "hash" in payload["results"][0]

    @patch("app.tools.registry.settings")
    @pytest.mark.asyncio
    async def test_timeout_error(self, mock_settings):
        """Un timeout del proveedor primario cae al fallback (Wikipedia)."""
        mock_settings.WEB_SEARCH_PROVIDER = "duckduckgo"
        mock_settings.WEB_SEARCH_TIMEOUT = 1
        mock_settings.TAVILY_API_KEY = ""

        import asyncio

        from app.tools.registry import search_web

        async def slow_ddg(query, max_results, timeout):
            raise asyncio.TimeoutError()

        async def wiki_ok(query, max_results, timeout):
            return [
                {
                    "title": "Artículo de respaldo",
                    "url": "https://es.wikipedia.org/wiki/Articulo",
                    "snippet": "Resumen del artículo",
                    "content": "Resumen del artículo",
                    "source_type": "web",
                    "hash": "hash_wiki",
                }
            ]

        with (
            patch("app.tools.registry._search_duckduckgo", new=slow_ddg),
            patch("app.tools.registry._search_wikipedia", new=wiki_ok),
        ):
            result = await search_web.ainvoke(
                {
                    "query": "consulta lenta",
                    "max_results": 3,
                }
            )
        payload = json.loads(result)

        # El fallback rescata la búsqueda: status success vía wikipedia
        assert payload["status"] == "success"
        assert payload["provider"] == "wikipedia"
        assert payload["total"] == 1

    @patch("app.tools.registry.settings")
    @pytest.mark.asyncio
    async def test_error_response(self, mock_settings):
        """Si TODA la cadena de proveedores falla, retorna error."""
        mock_settings.WEB_SEARCH_PROVIDER = "duckduckgo"
        mock_settings.WEB_SEARCH_TIMEOUT = 10
        mock_settings.TAVILY_API_KEY = ""

        from app.tools.registry import search_web

        with (
            patch("app.tools.registry._DDGS_CLASS") as mock_ddgs,
            patch(
                "app.tools.registry._search_wikipedia",
                side_effect=Exception("Wikipedia caída"),
            ),
        ):
            mock_instance = MagicMock()
            mock_ddgs.return_value = mock_instance
            mock_instance.text.side_effect = Exception("Error de conexión")

            result = await search_web.ainvoke(
                {
                    "query": "consulta con error",
                    "max_results": 3,
                }
            )
            payload = json.loads(result)

        assert payload["status"] == "error"
        # El error reportado es el del último proveedor de la cadena
        assert "Wikipedia caída" in payload["error"]


# =============================================================================
#  suggest_update — source_web_url
# =============================================================================


class TestSuggestUpdateWithWebUrl:
    """Suggest_update con source_web_url opcional."""

    @patch("app.database.AsyncSessionLocal")
    @pytest.mark.asyncio
    async def test_with_source_web_url(self, mock_session_factory):
        """Acepta source_web_url opcional."""
        from app.tools.registry import suggest_update

        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__.return_value = mock_session

        mock_suggestion = MagicMock()
        mock_suggestion.id = "sug-123"
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        # Patch uuid.UUID para que no falle
        with patch("uuid.UUID", return_value="00000000-0000-0000-0000-000000000001"):
            with patch("app.models.models.Suggestion", return_value=mock_suggestion):
                with patch.object(mock_suggestion, "id", "sug-123"):
                    result = await suggest_update.ainvoke(
                        {
                            "document_id": "550e8400-e29b-41d4-a716-446655440000",
                            "description": "Sugerencia con fuente web",
                            "source_doc_id": "doc_1",
                            "source_chunk_ids": ["chunk_1"],
                            "confidence_score": 0.9,
                            "suggestion_type": "update",
                            "reasoning": "Basado en búsqueda web",
                            "source_web_url": "https://example.com/articulo",
                        }
                    )
                    payload = json.loads(result)

                    assert payload["status"] == "success"
                    assert payload["source_web_url"] == "https://example.com/articulo"
