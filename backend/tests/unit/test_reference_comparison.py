"""
Tests del nodo reference_comparison_node: comparación del contenido del
curso contra el corpus de documentos de referencia (buenas prácticas).
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.nodes import reference_comparison_node

pytestmark = pytest.mark.asyncio


def _mock_session_factory():
    session = AsyncMock()
    session.add = MagicMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory, session


def _make_state(doc_id: str) -> dict:
    return {
        "document_ids": [doc_id],
        "documents_text": {},
        "chunks": [
            {
                "chroma_id": f"{doc_id}_chunk_0",
                "chunk_index": 0,
                "text": "def process(data): return data  # sin type hints ni docstring",
                "token_count": 15,
            }
        ],
        "messages": [],
        "suggestions": [],
        "redundancy_findings": [],
        "inconsistency_findings": [],
        "terminology_map": {},
        "web_search_results": [],
        "error": None,
    }


def _mock_collection(ref_doc_id: str):
    """Colección Chroma mockeada: corpus de referencia con 1 match relevante.

    El nodo calcula similitud coseno sobre embeddings directamente
    (embeddings idénticos → coseno 1.0 ≥ threshold).
    """
    collection = MagicMock()

    def get_side_effect(*args, **kwargs):
        if kwargs.get("where") == {"category": "reference"}:
            # Corpus de referencia completo con embeddings
            return {
                "ids": [f"{ref_doc_id}_chunk_0"],
                "embeddings": [[0.1, 0.2, 0.3]],
                "documents": ["Toda función debe tener type hints y docstring."],
                "metadatas": [{"doc_id": ref_doc_id, "category": "reference"}],
            }
        # Embedding almacenado del chunk curado (idéntico → coseno 1.0)
        return {"embeddings": [[0.1, 0.2, 0.3]]}

    collection.get.side_effect = get_side_effect
    return collection


async def test_creates_update_suggestion_from_reference():
    """Genera sugerencia type=update citando la referencia como fuente."""
    doc_id = str(uuid.uuid4())
    ref_doc_id = str(uuid.uuid4())
    factory, session = _mock_session_factory()

    with (
        patch("app.agents.nodes._get_llm_for_node", return_value=MagicMock()),
        patch(
            "app.rag.embeddings.get_chroma_collection",
            return_value=_mock_collection(ref_doc_id),
        ),
        patch(
            "app.tools.registry.compare_against_references_with_llm",
            new=AsyncMock(
                return_value=[
                    {
                        "pair_index": 0,
                        "recommendation": "Agregar type hints y docstring a process()",
                        "reasoning": "La referencia exige type hints en toda función.",
                        "confidence": 0.82,
                    }
                ]
            ),
        ) as mock_compare,
        patch("app.agents.nodes.AsyncSessionLocal", new=factory),
    ):
        result = await reference_comparison_node(_make_state(doc_id))

    # UNA sola llamada al LLM con los pares
    assert mock_compare.await_count == 1
    pairs_arg = mock_compare.await_args.args[0]
    assert pairs_arg[0]["curated_chunk_id"] == f"{doc_id}_chunk_0"
    assert pairs_arg[0]["reference_doc_id"] == ref_doc_id

    # Sugerencia persistida y reflejada en el estado
    assert session.add.call_count == 1
    persisted = session.add.call_args.args[0]
    assert persisted.source_doc_id == ref_doc_id  # fuente = referencia (badge 📚)
    assert f"{doc_id}_chunk_0" in persisted.source_chunk_ids
    assert f"{ref_doc_id}_chunk_0" in persisted.source_chunk_ids

    suggestions = result["suggestions"]
    assert len(suggestions) == 1
    assert suggestions[0]["type"] == "update"
    assert suggestions[0]["source_type"] == "reference"
    assert suggestions[0]["confidence_score"] == 0.82


async def test_skips_without_llm():
    """Sin LLM el nodo se omite (la comparación semántica requiere modelo)."""
    with patch("app.agents.nodes._get_llm_for_node", return_value=None):
        result = await reference_comparison_node(_make_state(str(uuid.uuid4())))
    assert result == {}


async def test_skips_without_reference_corpus():
    """Sin corpus de referencia en Chroma no hay nada que comparar."""
    collection = MagicMock()
    collection.get.return_value = {"ids": []}  # probe vacío

    with (
        patch("app.agents.nodes._get_llm_for_node", return_value=MagicMock()),
        patch(
            "app.rag.embeddings.get_chroma_collection", return_value=collection
        ),
        patch(
            "app.tools.registry.compare_against_references_with_llm",
            new=AsyncMock(return_value=[]),
        ) as mock_compare,
    ):
        result = await reference_comparison_node(_make_state(str(uuid.uuid4())))

    assert result == {}
    mock_compare.assert_not_awaited()


async def test_no_suggestions_when_content_complies():
    """Si el LLM no reporta desviaciones, no se crean sugerencias."""
    doc_id = str(uuid.uuid4())
    ref_doc_id = str(uuid.uuid4())

    with (
        patch("app.agents.nodes._get_llm_for_node", return_value=MagicMock()),
        patch(
            "app.rag.embeddings.get_chroma_collection",
            return_value=_mock_collection(ref_doc_id),
        ),
        patch(
            "app.tools.registry.compare_against_references_with_llm",
            new=AsyncMock(return_value=[]),
        ),
    ):
        result = await reference_comparison_node(_make_state(doc_id))

    assert result == {}
