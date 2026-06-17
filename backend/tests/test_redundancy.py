"""
Tests para #14/#15 — Algoritmo redundancia (coseno > 0.90) + confidence score.

Verifica:
  - _cosine_similarity con vectores normales, iguales, ortogonales y cero
  - _compute_confidence_score con distintos escenarios
  - detect_redundancy con ChromaDB mockeada
  - detect_redundancy_bulk con múltiples chunks
  - scan_all_redundancy con límite de comparaciones
  - Edge cases: chunk no encontrado, sin embedding, colección vacía
"""

from unittest.mock import MagicMock, patch

import pytest
from app.config import settings
from app.rag.redundancy import (
    RedundancyReport,
    RedundancyResult,
    _compute_confidence_score,
    _cosine_similarity,
    _index_chunks_by_id,
    _safe_get_content,
    _safe_get_embeddings,
    _safe_get_metadata,
    detect_redundancy,
    detect_redundancy_bulk,
    detect_redundancy_report,
    redundancy_report_to_json,
    scan_all_redundancy,
)

# ── Tests de helpers de bajo nivel ────────────────────────────────────────────


class TestCosineSimilarity:
    def test_identical_vectors(self):
        a = [1.0, 2.0, 3.0]
        assert _cosine_similarity(a, a) == 1.0

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert _cosine_similarity(a, b) == 0.0

    def test_similar_vectors(self):
        a = [1.0, 2.0, 3.0]
        b = [1.1, 2.1, 3.1]
        sim = _cosine_similarity(a, b)
        assert 0.99 < sim <= 1.0

    def test_opposite_vectors(self):
        a = [1.0, 2.0]
        b = [-1.0, -2.0]
        sim = _cosine_similarity(a, b)
        assert sim == -1.0

    def test_zero_vector_returns_zero(self):
        a = [0.0, 0.0, 0.0]
        b = [1.0, 2.0, 3.0]
        assert _cosine_similarity(a, b) == 0.0

    def test_both_zero_vectors(self):
        a = [0.0, 0.0]
        b = [0.0, 0.0]
        assert _cosine_similarity(a, b) == 0.0

    def test_different_dimensions(self):
        a = [1.0, 2.0, 3.0]
        b = [1.0, 2.0]
        # zip trunca al más corto, no debería explotar
        sim = _cosine_similarity(a, b)
        assert isinstance(sim, float)


class TestComputeConfidenceScore:
    def test_perfect_conditions(self):
        """Similitud alta, chunks largos, contenido consistente."""
        score = _compute_confidence_score(
            similarity=0.95,
            token_count_a=100,
            token_count_b=120,
            content_a="palabras significativas con contenido relevante",
            content_b="otro texto sustancial con información valiosa",
        )
        assert 0.80 <= score <= 1.0

    def test_low_similarity_penalizes(self):
        """Baja similitud debe bajar el score."""
        score_low = _compute_confidence_score(
            similarity=0.50,
            token_count_a=100,
            token_count_b=100,
            content_a="texto A con contenido significativo para la prueba",
            content_b="texto B con contenido diferente pero sustancial",
        )
        score_high = _compute_confidence_score(
            similarity=0.95,
            token_count_a=100,
            token_count_b=100,
            content_a="texto A con contenido significativo para la prueba",
            content_b="texto B con contenido diferente pero sustancial",
        )
        assert score_low < score_high

    def test_short_chunks_penalized(self):
        """Chunks muy cortos deben reducir el score."""
        score_short = _compute_confidence_score(
            similarity=0.90,
            token_count_a=5,
            token_count_b=10,
            content_a="corto",
            content_b="breve texto",
        )
        score_long = _compute_confidence_score(
            similarity=0.90,
            token_count_a=100,
            token_count_b=120,
            content_a="texto A con contenido significativo para la prueba",
            content_b="texto B con contenido diferente pero sustancial",
        )
        assert score_short < score_long

    def test_inconsistent_content_penalized(self):
        """Alta proporción de palabras cortas (relleno) debe reducir el score."""
        score_bad = _compute_confidence_score(
            similarity=0.90,
            token_count_a=100,
            token_count_b=100,
            content_a="a b c d e f g h i j k l m n o p",  # puras letras sueltas
            content_b="q r s t u v w x y z a b c d e f",
        )
        score_good = _compute_confidence_score(
            similarity=0.90,
            token_count_a=100,
            token_count_b=100,
            content_a="contenido sustancial con palabras significativas",
            content_b="otro texto informativo con vocabulario relevante",
        )
        assert score_bad < score_good

    def test_score_clamped_to_zero(self):
        """El score no debe bajar de 0.0."""
        score = _compute_confidence_score(
            similarity=-1.0,
            token_count_a=1,
            token_count_b=1,
            content_a="a",
            content_b="b",
        )
        assert score >= 0.0

    def test_score_clamped_to_one(self):
        """El score no debe superar 1.0."""
        score = _compute_confidence_score(
            similarity=1.0,
            token_count_a=1000,
            token_count_b=1000,
            content_a="texto con contenido significativo " * 10,
            content_b="otro texto sustancial " * 10,
        )
        assert score <= 1.0


class TestSafeAccessors:
    def test_safe_get_embeddings(self):
        data = {"embeddings": [[1.0, 2.0], [3.0, 4.0]]}
        assert _safe_get_embeddings(data, 0) == [1.0, 2.0]
        assert _safe_get_embeddings(data, 5) is None
        assert _safe_get_embeddings({}, 0) is None
        assert _safe_get_embeddings({"embeddings": None}, 0) is None

    def test_safe_get_content(self):
        data = {"documents": ["hola", "mundo"]}
        assert _safe_get_content(data, 0) == "hola"
        assert _safe_get_content(data, 5) == ""
        assert _safe_get_content({}, 0) == ""

    def test_safe_get_metadata(self):
        data = {"metadatas": [{"key": "val"}, {"key2": "val2"}]}
        assert _safe_get_metadata(data, 0) == {"key": "val"}
        assert _safe_get_metadata(data, 5) == {}
        assert _safe_get_metadata({}, 0) == {}


class TestIndexChunksById:
    def test_basic_indexing(self):
        data = {
            "ids": ["chunk1", "chunk2"],
            "embeddings": [[1.0], [2.0]],
            "metadatas": [{"doc_id": "doc1"}, {"doc_id": "doc2"}],
            "documents": ["texto1", "texto2"],
        }
        result = _index_chunks_by_id(data)
        assert "chunk1" in result
        assert "chunk2" in result
        assert result["chunk1"]["embedding"] == [1.0]
        assert result["chunk2"]["metadata"]["doc_id"] == "doc2"

    def test_empty_data(self):
        assert _index_chunks_by_id({}) == {}


# ── Tests de detect_redundancy (con ChromaDB mockeada) ────────────────────────


def _make_mock_collection():
    """Crea un MagicMock que simula una colección ChromaDB con chunks."""
    docs = [
        {
            "id": "chunk_a",
            "embedding": [0.1, 0.2, 0.3],
            "doc_id": "doc_1",
            "chunk_index": 0,
            "token_count": 80,
            "content": "Introducción a la inteligencia artificial en educación",
        },
        {
            "id": "chunk_b",
            "embedding": [0.15, 0.25, 0.35],  # similar a chunk_a
            "doc_id": "doc_1",
            "chunk_index": 1,
            "token_count": 90,
            "content": "Fundamentos de IA aplicada al aprendizaje universitario",
        },
        {
            "id": "chunk_c",
            "embedding": [0.9, 0.8, 0.7],  # muy diferente
            "doc_id": "doc_2",
            "chunk_index": 0,
            "token_count": 75,
            "content": "Historia del arte renacentista en Europa del sur",
        },
        {
            "id": "chunk_d",
            "embedding": [0.12, 0.22, 0.32],  # muy similar a chunk_a
            "doc_id": "doc_3",
            "chunk_index": 0,
            "token_count": 85,
            "content": "Machine learning en contextos educativos universitarios",
        },
    ]
    mock_col = MagicMock()

    def get_side_effect(ids=None, include=None, where=None):
        if ids:
            selected = [d for d in docs if d["id"] in ids]
        else:
            selected = docs
        return {
            "ids": [d["id"] for d in selected],
            "embeddings": [d["embedding"] for d in selected],
            "metadatas": [
                {
                    "doc_id": d["doc_id"],
                    "chunk_index": d["chunk_index"],
                    "token_count": d["token_count"],
                }
                for d in selected
            ],
            "documents": [d["content"] for d in selected],
        }

    mock_col.get.side_effect = get_side_effect
    return mock_col


@pytest.mark.asyncio
async def test_detect_redundancy_returns_list():
    """detect_redundancy debe retornar List[RedundancyResult] (no Report)."""
    with patch(
        "app.rag.embeddings.get_chroma_collection",
        return_value=_make_mock_collection(),
    ):
        results = await detect_redundancy(
            chunk_id="chunk_a",
            threshold=0.90,
        )
        assert isinstance(results, list)
        if results:
            assert isinstance(results[0], RedundancyResult)


@pytest.mark.asyncio
async def test_detect_redundancy_finds_similar_chunks():
    """Debe encontrar chunks con similitud > threshold."""
    with patch(
        "app.rag.embeddings.get_chroma_collection",
        return_value=_make_mock_collection(),
    ):
        # threshold bajo para forzar matches
        results = await detect_redundancy(
            chunk_id="chunk_a",
            threshold=0.80,
        )
        # chunk_b y chunk_d deberían matchear
        assert len(results) >= 2
        result_ids = {r.chunk_id_b for r in results}
        assert "chunk_b" in result_ids
        assert "chunk_d" in result_ids


@pytest.mark.asyncio
async def test_detect_redundancy_high_threshold():
    """Con threshold = 1.0 (máximo), no debe encontrar pares (vectores no idénticos)."""
    with patch(
        "app.rag.embeddings.get_chroma_collection",
        return_value=_make_mock_collection(),
    ):
        results = await detect_redundancy(
            chunk_id="chunk_a",
            threshold=1.0,
        )
        assert len(results) == 0


@pytest.mark.asyncio
async def test_detect_redundancy_chunk_not_found():
    """Chunk inexistente debe retornar lista vacía."""
    mock_col = MagicMock()
    mock_col.get.return_value = {
        "ids": [],
        "embeddings": [],
        "metadatas": [],
        "documents": [],
    }
    with patch(
        "app.rag.embeddings.get_chroma_collection",
        return_value=mock_col,
    ):
        results = await detect_redundancy(chunk_id="no_existe")
        assert results == []


@pytest.mark.asyncio
async def test_detect_redundancy_excludes_self():
    """Un chunk no debe aparecer como redundante consigo mismo."""
    with patch(
        "app.rag.embeddings.get_chroma_collection",
        return_value=_make_mock_collection(),
    ):
        results = await detect_redundancy(
            chunk_id="chunk_a",
            threshold=0.80,
        )
        for r in results:
            assert r.chunk_id_b != "chunk_a"


@pytest.mark.asyncio
async def test_detect_redundancy_excludes_same_doc():
    """Con include_same_doc=False, omite chunks del mismo documento."""
    with patch(
        "app.rag.embeddings.get_chroma_collection",
        return_value=_make_mock_collection(),
    ):
        results = await detect_redundancy(
            chunk_id="chunk_a",
            threshold=0.80,
            include_same_doc=False,
        )
        for r in results:
            assert r.doc_id_b != "doc_1"


@pytest.mark.asyncio
async def test_detect_redundancy_pairs_have_all_fields():
    """Cada RedundancyResult debe tener todos los campos requeridos."""
    with patch(
        "app.rag.embeddings.get_chroma_collection",
        return_value=_make_mock_collection(),
    ):
        results = await detect_redundancy(
            chunk_id="chunk_a",
            threshold=0.80,
        )
        for r in results:
            assert r.chunk_id_a == "chunk_a"
            assert isinstance(r.chunk_id_b, str)
            assert isinstance(r.similarity, float)
            assert 0.0 <= r.confidence_score <= 1.0
            assert isinstance(r.doc_id_a, str)
            assert isinstance(r.doc_id_b, str)
            assert isinstance(r.content_a_preview, str)
            assert isinstance(r.content_b_preview, str)
            assert isinstance(r.token_count_a, int)
            assert isinstance(r.token_count_b, int)


# ── Tests de detect_redundancy_report ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_detect_redundancy_report_structure():
    """detect_redundancy_report debe retornar un RedundancyReport completo."""
    with patch(
        "app.rag.embeddings.get_chroma_collection",
        return_value=_make_mock_collection(),
    ):
        report = await detect_redundancy_report(chunk_id="chunk_a", threshold=0.80)
        assert isinstance(report, RedundancyReport)
        assert report.query_chunk_id == "chunk_a"
        assert report.threshold == 0.80
        assert report.total_comparisons > 0
        assert report.pair_count == len(report.redundant_pairs)


# ── Tests de detect_redundancy_bulk ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_detect_redundancy_bulk_empty():
    """Lista vacía debe retornar lista vacía."""
    with patch("app.rag.embeddings.get_chroma_collection"):
        results = await detect_redundancy_bulk([])
        assert results == []


@pytest.mark.asyncio
async def test_detect_redundancy_bulk_multiple():
    """Debe procesar múltiples chunks y evitar pares duplicados A-B/B-A."""
    with patch(
        "app.rag.embeddings.get_chroma_collection",
        return_value=_make_mock_collection(),
    ):
        reports = await detect_redundancy_bulk(
            chunk_ids=["chunk_a", "chunk_b"],
            threshold=0.80,
        )
        assert len(reports) > 0
        # Verificar que no hay pares duplicados entre reportes
        seen = set()
        for report in reports:
            for pair in report.redundant_pairs:
                key = frozenset([pair.chunk_id_a, pair.chunk_id_b])
                assert key not in seen, f"Par duplicado encontrado: {key}"
                seen.add(key)


# ── Tests de scan_all_redundancy ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_all_redundancy_empty():
    """Colección vacía debe retornar lista vacía."""
    mock_col = MagicMock()
    mock_col.get.return_value = {
        "ids": [],
        "embeddings": [],
        "metadatas": [],
        "documents": [],
    }
    with patch(
        "app.rag.embeddings.get_chroma_collection",
        return_value=mock_col,
    ):
        results = await scan_all_redundancy(threshold=0.90)
        assert results == []


@pytest.mark.asyncio
async def test_scan_all_redundancy_single_chunk():
    """Un solo chunk debe retornar lista vacía."""
    mock_col = MagicMock()
    mock_col.get.return_value = {
        "ids": ["solo"],
        "embeddings": [[1.0, 2.0]],
        "metadatas": [{"doc_id": "doc_1", "chunk_index": 0, "token_count": 50}],
        "documents": ["contenido único"],
    }
    with patch(
        "app.rag.embeddings.get_chroma_collection",
        return_value=mock_col,
    ):
        results = await scan_all_redundancy(threshold=0.90)
        assert results == []


@pytest.mark.asyncio
async def test_scan_all_redundancy_global():
    """Debe encontrar pares redundantes a nivel global y ordenarlos."""
    with patch(
        "app.rag.embeddings.get_chroma_collection",
        return_value=_make_mock_collection(),
    ):
        results = await scan_all_redundancy(threshold=0.80, max_pairs=10)
        assert len(results) >= 2
        # Verificar orden descendente
        for i in range(len(results) - 1):
            assert results[i].similarity >= results[i + 1].similarity
        # Verificar que no incluye pares del mismo doc por defecto
        for r in results:
            assert r.doc_id_a != r.doc_id_b


# ── Tests de redundancy_report_to_json ────────────────────────────────────────


def test_redundancy_report_to_json():
    """Debe serializar correctamente a JSON."""
    pair = RedundancyResult(
        chunk_id_a="a",
        chunk_id_b="b",
        similarity=0.95,
        confidence_score=0.88,
        doc_id_a="doc1",
        doc_id_b="doc2",
        chunk_index_a=0,
        chunk_index_b=1,
        content_a_preview="texto A...",
        content_b_preview="texto B...",
        token_count_a=50,
        token_count_b=60,
    )
    report = RedundancyReport(
        query_chunk_id="a",
        threshold=0.9,
        total_comparisons=10,
        redundant_pairs=[pair],
        pair_count=1,
    )
    json_str = redundancy_report_to_json(report)
    assert "chunk_id_a" in json_str
    assert "chunk_id_b" in json_str
    assert "similarity" in json_str
    assert "confidence_score" in json_str
    assert "0.95" in json_str


# ── Tests de integración con config ───────────────────────────────────────────


def test_default_threshold_from_settings():
    """El threshold por defecto debe ser 0.90."""
    assert settings.REDUNDANCY_THRESHOLD == 0.90


def test_max_redundancy_comparisons_setting():
    """MAX_REDUNDANCY_COMPARISONS debe estar definido."""
    assert hasattr(settings, "MAX_REDUNDANCY_COMPARISONS")
    assert settings.MAX_REDUNDANCY_COMPARISONS > 0
