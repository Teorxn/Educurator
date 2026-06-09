"""
Tests unitarios para el algoritmo de detección de redundancia (#14).

Cubre:
  - _cosine_similarity
  - _compute_confidence_score
  - RedundancyResult schema validation
  - detect_redundancy (con mocks de ChromaDB)
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import settings
from app.rag.redundancy import (
    RedundancyReport,
    RedundancyResult,
    _compute_confidence_score,
    _cosine_similarity,
    detect_redundancy,
    detect_redundancy_bulk,
    redundancy_report_to_json,
)

# ── Tests: _cosine_similarity ─────────────────────────────────────────────────


class TestCosineSimilarity:
    def test_identical_vectors(self):
        a = [1.0, 2.0, 3.0]
        b = [1.0, 2.0, 3.0]
        assert _cosine_similarity(a, b) == 1.0

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert _cosine_similarity(a, b) == 0.0

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert _cosine_similarity(a, b) == -1.0

    def test_zero_vector(self):
        a = [0.0, 0.0]
        b = [1.0, 0.0]
        assert _cosine_similarity(a, b) == 0.0

    def test_partial_similarity(self):
        a = [1.0, 2.0, 3.0]
        b = [1.0, 2.0, 0.0]
        result = _cosine_similarity(a, b)
        assert 0.5 < result < 1.0

    def test_rounding(self):
        a = [1.0, 1.0]
        b = [1.0, 0.9999]
        result = _cosine_similarity(a, b)
        # Verificar que redondea a 4 decimales
        assert isinstance(result, float)
        assert len(str(result).split(".")[1]) <= 4


# ── Tests: _compute_confidence_score ─────────────────────────────────────────


class TestConfidenceScore:
    def test_perfect_confidence(self):
        """Similitud 1.0, chunks largos y contenido consistente."""
        score = _compute_confidence_score(
            similarity=1.0,
            token_count_a=200,
            token_count_b=200,
            content_a="Python es un lenguaje de programación interpretado",
            content_b="Python es un lenguaje de programación interpretado",
        )
        # No puede ser 1.0 por la penalización de consistencia
        # (palabras cortas como 'es', 'un', 'de' reducen el factor)
        assert 0.90 <= score < 1.0

    def test_high_similarity_reduces_confidence(self):
        """Menor similitud → menor confianza."""
        high = _compute_confidence_score(0.95, 100, 100, "hola mundo", "hola mundo")
        low = _compute_confidence_score(0.80, 100, 100, "hola mundo", "hola mundo")
        assert high > low

    def test_short_chunks_penalized(self):
        """Chunks muy cortos obtienen menor confianza."""
        short = _compute_confidence_score(0.95, 10, 10, "a b c", "a b c")
        long = _compute_confidence_score(
            0.95, 100, 100, "palabra larga significado", "palabra larga significado"
        )
        assert short < long

    def test_score_range(self):
        """El score siempre está entre 0.0 y 1.0."""
        score = _compute_confidence_score(0.0, 0, 0, "", "")
        assert 0.0 <= score <= 1.0

        score = _compute_confidence_score(1.0, 512, 512, "a" * 500, "a" * 500)
        assert 0.0 <= score <= 1.0

    def test_rounding_precision(self):
        """El score se redondea a 4 decimales."""
        score = _compute_confidence_score(
            0.91234, 100, 100, "test content here", "test content here"
        )
        assert isinstance(score, float)
        decimal_part = str(score).split(".")[1] if "." in str(score) else ""
        assert len(decimal_part) <= 4


# ── Tests: RedundancyResult schema ───────────────────────────────────────────


class TestRedundancyResultSchema:
    def test_valid_result(self):
        result = RedundancyResult(
            chunk_id_a="chunk_1",
            chunk_id_b="chunk_2",
            similarity=0.95,
            confidence_score=0.92,
            doc_id_a="doc_1",
            doc_id_b="doc_2",
            chunk_index_a=0,
            chunk_index_b=1,
            content_a_preview="contenido del primer chunk...",
            content_b_preview="contenido del segundo chunk...",
            token_count_a=100,
            token_count_b=150,
        )
        assert result.chunk_id_a == "chunk_1"
        assert result.similarity == 0.95
        assert result.confidence_score == 0.92
        assert result.token_count_a == 100

    def test_frozen_model(self):
        """RedundancyResult debe ser inmutable."""
        result = RedundancyResult(
            chunk_id_a="a",
            chunk_id_b="b",
            similarity=0.9,
            confidence_score=0.8,
            doc_id_a="d1",
            doc_id_b="d2",
            chunk_index_a=0,
            chunk_index_b=0,
            content_a_preview="a",
            content_b_preview="b",
            token_count_a=10,
            token_count_b=10,
        )
        with pytest.raises((TypeError, ValueError)):
            result.similarity = 0.5

    def test_similarity_bounds(self):
        """similarity debe estar entre 0.0 y 1.0."""
        with pytest.raises(ValueError):
            RedundancyResult(
                chunk_id_a="a",
                chunk_id_b="b",
                similarity=1.5,
                confidence_score=0.5,
                doc_id_a="d1",
                doc_id_b="d2",
                chunk_index_a=0,
                chunk_index_b=0,
                content_a_preview="a",
                content_b_preview="b",
                token_count_a=10,
                token_count_b=10,
            )

    def test_confidence_score_bounds(self):
        """confidence_score debe estar entre 0.0 y 1.0."""
        with pytest.raises(ValueError):
            RedundancyResult(
                chunk_id_a="a",
                chunk_id_b="b",
                similarity=0.5,
                confidence_score=-0.1,
                doc_id_a="d1",
                doc_id_b="d2",
                chunk_index_a=0,
                chunk_index_b=0,
                content_a_preview="a",
                content_b_preview="b",
                token_count_a=10,
                token_count_b=10,
            )


# ── Tests: RedundancyReport schema ──────────────────────────────────────────


class TestRedundancyReportSchema:
    def test_empty_report(self):
        report = RedundancyReport(
            query_chunk_id="chunk_1",
            threshold=0.90,
            total_comparisons=0,
            redundant_pairs=[],
            pair_count=0,
        )
        assert report.pair_count == 0
        assert len(report.redundant_pairs) == 0

    def test_report_with_pairs(self):
        pair = RedundancyResult(
            chunk_id_a="a",
            chunk_id_b="b",
            similarity=0.95,
            confidence_score=0.9,
            doc_id_a="d1",
            doc_id_b="d2",
            chunk_index_a=0,
            chunk_index_b=0,
            content_a_preview="a",
            content_b_preview="b",
            token_count_a=10,
            token_count_b=10,
        )
        report = RedundancyReport(
            query_chunk_id="chunk_1",
            threshold=0.90,
            total_comparisons=10,
            redundant_pairs=[pair],
            pair_count=1,
        )
        assert report.pair_count == 1


# ── Tests: redundancy_report_to_json ─────────────────────────────────────────


class TestReportToJson:
    def test_empty_report_serialization(self):
        report = RedundancyReport(
            query_chunk_id="chunk_1",
            threshold=0.90,
            total_comparisons=0,
            redundant_pairs=[],
            pair_count=0,
        )
        json_str = redundancy_report_to_json(report)
        data = json.loads(json_str)
        assert data["status"] == "success"
        assert data["pair_count"] == 0
        assert data["redundant_pairs"] == []

    def test_report_serialization_with_pairs(self):
        pair = RedundancyResult(
            chunk_id_a="a",
            chunk_id_b="b",
            similarity=0.95,
            confidence_score=0.9,
            doc_id_a="d1",
            doc_id_b="d2",
            chunk_index_a=0,
            chunk_index_b=0,
            content_a_preview="a",
            content_b_preview="b",
            token_count_a=10,
            token_count_b=10,
        )
        report = RedundancyReport(
            query_chunk_id="chunk_1",
            threshold=0.90,
            total_comparisons=10,
            redundant_pairs=[pair],
            pair_count=1,
        )
        data = json.loads(redundancy_report_to_json(report))
        assert len(data["redundant_pairs"]) == 1
        assert data["pair_count"] == 1
        assert data["redundant_pairs"][0]["chunk_id_a"] == "a"


# ── Tests: detect_redundancy (mocked ChromaDB) ──────────────────────────────


class FakeCollection:
    """Mock de colección ChromaDB para pruebas."""

    def __init__(self, chunks: list[dict]):
        self._chunks = chunks  # Cada chunk: {id, embedding, document, metadata}

    def get(self, ids=None, where=None, include=None):
        if ids is not None:
            filtered = [c for c in self._chunks if c["id"] in ids]
        elif where is not None and "doc_id" in where:
            filtered = [
                c
                for c in self._chunks
                if c.get("metadata", {}).get("doc_id") == where["doc_id"]
            ]
        else:
            filtered = list(self._chunks)

        result = {
            "ids": [c["id"] for c in filtered],
            "embeddings": [c.get("embedding") for c in filtered]
            if include and "embeddings" in include
            else None,
            "documents": [c.get("document", "") for c in filtered]
            if include and "documents" in include
            else None,
            "metadatas": [c.get("metadata", {}) for c in filtered]
            if include and "metadatas" in include
            else None,
            "distances": None,
        }
        # Si no embeddings, poner None
        if result["embeddings"] and any(e is None for e in result["embeddings"]):
            result["embeddings"] = None
        return result

    def query(self, query_embeddings, n_results, include):
        return {"ids": [[]], "distances": [[]], "documents": [[]], "metadatas": [[]]}


def _make_chunk(
    chunk_id: str,
    doc_id: str,
    text: str,
    embedding: list[float],
    chunk_index: int = 0,
    token_count: int = 100,
):
    return {
        "id": chunk_id,
        "embedding": embedding,
        "document": text,
        "metadata": {
            "doc_id": doc_id,
            "chunk_index": chunk_index,
            "token_count": token_count,
        },
    }


@pytest.mark.asyncio
class TestDetectRedundancy:
    @patch("app.rag.embeddings.get_chroma_collection")
    async def test_no_chunk_found(self, mock_get_collection):
        """Si el chunk no existe, retorna reporte vacío."""
        mock_collection = FakeCollection([])
        mock_get_collection.return_value = mock_collection

        report = await detect_redundancy(chunk_id="nonexistent")
        assert report.pair_count == 0
        assert report.total_comparisons == 0

    @patch("app.rag.embeddings.get_chroma_collection")
    async def test_no_other_chunks(self, mock_get_collection):
        """Si solo hay un chunk, no puede haber redundancia."""
        mock_collection = FakeCollection(
            [
                _make_chunk("chunk_1", "doc_1", "contenido de prueba", [1.0, 0.0, 0.0]),
            ]
        )
        mock_get_collection.return_value = mock_collection

        report = await detect_redundancy(chunk_id="chunk_1")
        assert report.pair_count == 0
        assert report.total_comparisons == 0  # solo hay sí mismo

    @patch("app.rag.embeddings.get_chroma_collection")
    async def test_identical_chunks_detected(self, mock_get_collection):
        """Chunks idénticos deben detectarse como redundantes."""
        mock_collection = FakeCollection(
            [
                _make_chunk(
                    "chunk_1", "doc_1", "Python es un lenguaje", [1.0, 0.0, 0.0]
                ),
                _make_chunk(
                    "chunk_2", "doc_1", "Python es un lenguaje", [1.0, 0.0, 0.0]
                ),
            ]
        )
        mock_get_collection.return_value = mock_collection

        report = await detect_redundancy(chunk_id="chunk_1")
        assert report.pair_count == 1
        assert report.redundant_pairs[0].chunk_id_b == "chunk_2"
        assert report.redundant_pairs[0].similarity == 1.0

    @patch("app.rag.embeddings.get_chroma_collection")
    async def test_below_threshold_not_reported(self, mock_get_collection):
        """Chunks con similitud por debajo del threshold no se reportan."""
        # Crear 3 chunks: 2 iguales y 1 diferente
        mock_collection = FakeCollection(
            [
                _make_chunk(
                    "chunk_1", "doc_1", "Python es un lenguaje", [1.0, 0.0, 0.0]
                ),
                _make_chunk(
                    "chunk_2", "doc_1", "Python es un lenguaje", [0.99, 0.01, 0.0]
                ),
                _make_chunk(
                    "chunk_3", "doc_1", "JavaScript es otro lenguaje", [0.1, 0.9, 0.1]
                ),
            ]
        )
        mock_get_collection.return_value = mock_collection

        report = await detect_redundancy(chunk_id="chunk_1", threshold=0.90)
        assert report.pair_count == 1  # chunk_1 vs chunk_2
        for pair in report.redundant_pairs:
            assert pair.similarity > 0.90

    @patch("app.rag.embeddings.get_chroma_collection")
    async def test_threshold_configurable(self, mock_get_collection):
        """El threshold debe ser configurable."""
        mock_collection = FakeCollection(
            [
                _make_chunk("chunk_1", "doc_1", "contenido A", [1.0, 0.0]),
                _make_chunk("chunk_2", "doc_1", "contenido B", [0.85, 0.15]),
                _make_chunk("chunk_3", "doc_1", "contenido C", [0.5, 0.5]),
            ]
        )
        mock_get_collection.return_value = mock_collection

        # threshold = 0.80 → 1 par (chunk_1 vs chunk_2, sim ~0.93)
        report_80 = await detect_redundancy(chunk_id="chunk_1", threshold=0.80)
        pairs_80 = report_80.pair_count

        # threshold = 0.95 → 0 pares
        report_95 = await detect_redundancy(chunk_id="chunk_1", threshold=0.95)
        pairs_95 = report_95.pair_count

        assert pairs_80 >= pairs_95

    @patch("app.rag.embeddings.get_chroma_collection")
    async def test_confidence_score_included(self, mock_get_collection):
        """Cada par redundante debe incluir confidence_score."""
        mock_collection = FakeCollection(
            [
                _make_chunk(
                    "chunk_1",
                    "doc_1",
                    "Python es un lenguaje de programación",
                    [1.0, 0.0, 0.0],
                ),
                _make_chunk(
                    "chunk_2",
                    "doc_2",
                    "Python es un lenguaje de programación",
                    [0.99, 0.01, 0.0],
                ),
            ]
        )
        mock_get_collection.return_value = mock_collection

        report = await detect_redundancy(chunk_id="chunk_1")
        assert report.pair_count >= 1
        for pair in report.redundant_pairs:
            assert 0.0 <= pair.confidence_score <= 1.0

    @patch("app.rag.embeddings.get_chroma_collection")
    async def test_same_doc_exclusion(self, mock_get_collection):
        """include_same_doc=False debe excluir chunks del mismo documento."""
        mock_collection = FakeCollection(
            [
                _make_chunk("chunk_1", "doc_1", "contenido idéntico", [1.0, 0.0]),
                _make_chunk("chunk_2", "doc_1", "contenido idéntico", [0.99, 0.01]),
                _make_chunk("chunk_3", "doc_2", "contenido idéntico", [0.98, 0.02]),
            ]
        )
        mock_get_collection.return_value = mock_collection

        report_same = await detect_redundancy("chunk_1", include_same_doc=True)
        report_no_same = await detect_redundancy("chunk_1", include_same_doc=False)

        assert report_same.pair_count > report_no_same.pair_count

    @patch("app.rag.embeddings.get_chroma_collection")
    async def test_max_pairs_limit(self, mock_get_collection):
        """max_pairs debe limitar la cantidad de resultados."""
        chunks = [
            _make_chunk(f"chunk_{i}", "doc_1", f"contenido repetido {i}", [1.0, 0.0])
            for i in range(10)
        ]
        chunks[0] = _make_chunk("chunk_0", "doc_1", "contenido original", [1.0, 0.0])

        mock_collection = FakeCollection(chunks)
        mock_get_collection.return_value = mock_collection

        report = await detect_redundancy("chunk_0", max_pairs=3)
        assert report.pair_count <= 3


# ── Tests: detect_redundancy_bulk ────────────────────────────────────────────


@pytest.mark.asyncio
class TestDetectRedundancyBulk:
    @patch("app.rag.embeddings.get_chroma_collection")
    async def test_bulk_no_duplicates(self, mock_get_collection):
        """Bulk no debe reportar pares duplicados (A-B y B-A)."""
        mock_collection = FakeCollection(
            [
                _make_chunk("chunk_1", "doc_1", "contenido A", [1.0, 0.0, 0.0]),
                _make_chunk("chunk_2", "doc_1", "contenido A", [0.98, 0.02, 0.0]),
                _make_chunk("chunk_3", "doc_2", "contenido B", [0.1, 0.9, 0.1]),
            ]
        )
        mock_get_collection.return_value = mock_collection

        reports = await detect_redundancy_bulk(
            chunk_ids=["chunk_1", "chunk_2", "chunk_3"],
        )

        # Verificar que no hay pares duplicados
        all_pairs = set()
        for report in reports:
            for pair in report.redundant_pairs:
                pair_key = frozenset([pair.chunk_id_a, pair.chunk_id_b])
                assert pair_key not in all_pairs, f"Par duplicado: {pair_key}"
                all_pairs.add(pair_key)


# ── Test: configuración REDUNDANCY_THRESHOLD ────────────────────────────────


class TestRedundancyThresholdConfig:
    def test_default_threshold(self):
        """El threshold por defecto debe ser 0.90."""
        assert settings.REDUNDANCY_THRESHOLD == 0.90

    def test_threshold_used_by_detect(self):
        """detect_redundancy debe usar settings.REDUNDANCY_THRESHOLD por defecto."""
        # Verificar que el valor de config se usa cuando no se pasa threshold
        import inspect

        from app.rag.redundancy import detect_redundancy

        sig = inspect.signature(detect_redundancy)
        default_threshold = sig.parameters["threshold"].default
        assert default_threshold is None  # None significa "usa settings"
