"""
Tests para #60 — Detección de inconsistencias internas y terminológicas.

Verifica:
  - detect_numerical_inconsistencies con valores contradictorios
  - detect_structural_inconsistencies con encabezados, citas, secciones
  - detect_self_contradictions con chunks controlados (usa mock LLM)
  - detect_terminology_issues con términos extraídos
  - detect_all_inconsistencies integración
  - Edge cases: chunks vacíos, sin LLM, valores numéricos iguales
"""

import pytest
from app.rag.inconsistencies import (
    _contexts_describe_same_metric,
    _definitions_differ,
    _definitions_similar,
    _extract_numeric_entities,
    _normalize_unit,
    detect_all_inconsistencies,
    detect_numerical_inconsistencies,
    detect_structural_inconsistencies,
)

# ── Tests de helpers de bajo nivel ────────────────────────────────────────────


class TestNormalizeUnit:
    def test_hours(self):
        assert _normalize_unit("h") == "horas"
        assert _normalize_unit("hora") == "horas"
        assert _normalize_unit("horas") == "horas"

    def test_days(self):
        assert _normalize_unit("d") == "días"
        assert _normalize_unit("día") == "días"
        assert _normalize_unit("días") == "días"

    def test_unknown(self):
        assert _normalize_unit("metros") == "metros"

    def test_percentage(self):
        assert _normalize_unit("%") == "porcentaje"

    def test_credits(self):
        assert _normalize_unit("créditos") == "creditos"
        # La llamada real desde _extract_numeric_entities ya hace .lower()
        assert _normalize_unit("ects") == "ects"


class TestExtractNumericEntities:
    def test_extract_hours(self):
        text = "El curso dura 40 horas en total"
        entities = _extract_numeric_entities(text, "chunk_1")
        assert len(entities) >= 1
        e = entities[0]
        assert e["value"] == 40.0
        assert e["unit"] == "horas"

    def test_extract_percentage(self):
        text = "La nota mínima es 70%"
        entities = _extract_numeric_entities(text, "chunk_1")
        assert len(entities) >= 1
        assert entities[0]["value"] == 70.0
        assert entities[0]["unit"] == "%"

    def test_extract_multiple(self):
        text = "El curso tiene 6 módulos y dura 120 horas"
        entities = _extract_numeric_entities(text, "chunk_1")
        assert len(entities) >= 2

    def test_extract_with_decimal(self):
        text = "El costo es 150.50 euros por módulo"
        entities = _extract_numeric_entities(text, "chunk_1")
        assert len(entities) >= 1
        assert entities[0]["value"] == 150.50

    def test_no_numbers(self):
        text = "Este texto no tiene números relevantes"
        entities = _extract_numeric_entities(text, "chunk_1")
        assert len(entities) == 0

    def test_context_is_provided(self):
        text = "La duración total del programa es 120 horas aproximadamente"
        entities = _extract_numeric_entities(text, "chunk_1")
        assert len(entities) >= 1
        assert "duración" in entities[0]["context"]
        assert "120" in entities[0]["context"]


class TestContextsDescribeSameMetric:
    def test_same_metric_duration(self):
        ctx_a = "El curso tiene una duración de 40 horas"
        ctx_b = "La duración total del programa es 120 horas"
        assert _contexts_describe_same_metric(ctx_a, ctx_b)

    def test_different_metrics(self):
        ctx_a = "El costo del curso es 500 euros"
        ctx_b = "El número de estudiantes es 30"
        # Sin palabras clave compartidas de métrica
        assert not _contexts_describe_same_metric(ctx_a, ctx_b)

    def test_same_metric_credits(self):
        ctx_a = "El curso tiene 6 créditos ECTS"
        ctx_b = "Total de créditos del programa: 60"
        assert _contexts_describe_same_metric(ctx_a, ctx_b)


class TestDefinitionsCompare:
    def test_definitions_differ(self):
        a = "Síncrono significa que ocurre en tiempo real"
        b = "Síncrono se refiere a comunicación diferida"
        assert _definitions_differ(a, b)

    def test_definitions_same(self):
        a = "Síncrono significa que ocurre en tiempo real"
        b = "Síncrono es cuando algo ocurre en tiempo real con participantes"
        assert not _definitions_differ(a, b)

    def test_definitions_similar(self):
        a = "Evaluación continua es la evaluación progresiva del estudiante"
        b = "Evaluación continua es la evaluación progresiva del alumno"
        assert _definitions_similar(a, b)

    def test_definitions_not_similar(self):
        a = "Síncrono significa tiempo real"
        b = "Asíncrono significa tiempo diferido"
        assert not _definitions_similar(a, b)


# ── Tests de detección numérica ────────────────────────────────────────────


class TestDetectNumericalInconsistencies:
    def test_hours_mismatch(self):
        """Misma métrica (horas) con valores significativamente diferentes."""
        chunks = [
            {
                "chroma_id": "chunk_a",
                "doc_id": "doc_1",
                "text": "El curso tiene una duración de 40 horas totales",
                "content": "El curso tiene una duración de 40 horas totales",
            },
            {
                "chroma_id": "chunk_b",
                "doc_id": "doc_1",
                "text": "La duración del curso es 120 horas aproximadamente",
                "content": "La duración del curso es 120 horas aproximadamente",
            },
        ]
        findings = detect_numerical_inconsistencies(chunks)
        assert len(findings) >= 1
        assert findings[0]["type"] == "numerical"
        assert "horas" in findings[0]["description"]

    def test_no_conflict_same_value(self):
        """Mismos valores no deberían generar hallazgos."""
        chunks = [
            {
                "chroma_id": "chunk_a",
                "doc_id": "doc_1",
                "text": "El curso tiene 40 horas de duración",
                "content": "El curso tiene 40 horas de duración",
            },
            {
                "chroma_id": "chunk_b",
                "doc_id": "doc_1",
                "text": "Duración: 40 horas en total",
                "content": "Duración: 40 horas en total",
            },
        ]
        findings = detect_numerical_inconsistencies(chunks)
        # Valores idénticos no deberían generar hallazgos
        assert len(findings) == 0

    def test_different_units_no_conflict(self):
        """Unidades diferentes no se comparan entre sí."""
        chunks = [
            {
                "chroma_id": "chunk_a",
                "doc_id": "doc_1",
                "text": "El curso cuesta 500 euros",
                "content": "El curso cuesta 500 euros",
            },
            {
                "chroma_id": "chunk_b",
                "doc_id": "doc_1",
                "text": "El curso tiene 40 horas de duración",
                "content": "El curso tiene 40 horas de duración",
            },
        ]
        findings = detect_numerical_inconsistencies(chunks)
        # Unidades diferentes = grupos distintos = sin hallazgos
        assert len(findings) == 0

    def test_empty_chunks(self):
        """Chunks vacíos no deberían causar errores."""
        findings = detect_numerical_inconsistencies([])
        assert findings == []

    def test_different_docs_same_metric(self):
        """Documentos diferentes con la misma métrica."""
        chunks = [
            {
                "chroma_id": "chunk_a",
                "doc_id": "doc_1",
                "text": "El curso tiene una duración de 40 horas",
                "content": "El curso tiene una duración de 40 horas",
            },
            {
                "chroma_id": "chunk_b",
                "doc_id": "doc_2",
                "text": "El programa completo dura 100 horas",
                "content": "El programa completo dura 100 horas",
            },
        ]
        findings = detect_numerical_inconsistencies(chunks)
        # El contexto "duración" debería coincidir
        assert len(findings) >= 1


# ── Tests de detección estructural ──────────────────────────────────────────


class TestDetectStructuralInconsistencies:
    def test_missing_h1(self):
        """Documento sin h1."""
        chunks = [
            {
                "chroma_id": "chunk_a",
                "doc_id": "doc_1",
                "text": "## Introducción\n\nEste es el contenido\n### Objetivos\n\nObjetivo 1",
                "content": "## Introducción\n\nEste es el contenido\n### Objetivos\n\nObjetivo 1",
            },
        ]
        findings = detect_structural_inconsistencies(chunks)
        orphan = [
            f for f in findings if "encabezado de nivel 1" in f.get("description", "")
        ]
        assert len(orphan) >= 1

    def test_heading_jump(self):
        """Salto de nivel de encabezado."""
        chunks = [
            {
                "chroma_id": "chunk_a",
                "doc_id": "doc_1",
                "text": "# Título\n\nContenido\n### Subtítulo sin h2\n\nMás contenido",
                "content": "# Título\n\nContenido\n### Subtítulo sin h2\n\nMás contenido",
            },
        ]
        findings = detect_structural_inconsistencies(chunks)
        jumps = [f for f in findings if "Salto de nivel" in f.get("description", "")]
        assert len(jumps) >= 1

    def test_well_structured_document(self):
        """Documento bien estructurado."""
        chunks = [
            {
                "chroma_id": "chunk_a",
                "doc_id": "doc_1",
                "text": (
                    "# Título del Curso\n\n"
                    "## Introducción\n\nTexto introductorio\n\n"
                    "## Objetivos\n\nObjetivos del curso\n\n"
                    "## Contenido\n\nContenido del curso\n\n"
                    "## Evaluación\n\nMétodo de evaluación\n\n"
                    "## Bibliografía\n\nReferencias"
                ),
                "content": (
                    "# Título del Curso\n\n"
                    "## Introducción\n\nTexto introductorio\n\n"
                    "## Objetivos\n\nObjetivos del curso\n\n"
                    "## Contenido\n\nContenido del curso\n\n"
                    "## Evaluación\n\nMétodo de evaluación\n\n"
                    "## Bibliografía\n\nReferencias"
                ),
            },
        ]
        findings = detect_structural_inconsistencies(chunks)
        # No debería encontrar problemas estructurales graves
        orphan = [
            f for f in findings if "encabezado de nivel 1" in f.get("description", "")
        ]
        assert len(orphan) == 0

    def test_missing_section(self):
        """Documento al que le falta una sección obligatoria."""
        chunks = [
            {
                "chroma_id": "chunk_a",
                "doc_id": "doc_1",
                "text": "# Mi Curso\n\n## Introducción\n\nTexto sin metodología ni evaluación",
                "content": "# Mi Curso\n\n## Introducción\n\nTexto sin metodología ni evaluación",
            },
        ]
        findings = detect_structural_inconsistencies(chunks)
        missing = [
            f
            for f in findings
            if "secciones obligatorias no encontradas"
            in f.get("description", "").lower()
        ]
        assert len(missing) >= 1

    def test_empty_chunks(self):
        """Chunks vacíos no deberían causar errores."""
        findings = detect_structural_inconsistencies([])
        assert findings == []


# ── Tests de detección de auto-contradicción (con mock) ──────────────────────


@pytest.mark.asyncio
async def test_self_contradiction_no_llm():
    """Sin LLM, self_contradiction no debería ejecutarse."""
    from app.rag.inconsistencies import detect_self_contradictions

    chunks = [
        {
            "chroma_id": "chunk_a",
            "doc_id": "doc_1",
            "text": "El límite es 30 estudiantes",
            "content": "El límite es 30 estudiantes",
        },
        {
            "chroma_id": "chunk_b",
            "doc_id": "doc_1",
            "text": "El límite es 50 estudiantes",
            "content": "El límite es 50 estudiantes",
        },
    ]
    findings = await detect_self_contradictions(chunks)
    # Sin LLM configurado, no debería encontrar auto-contradicciones
    assert len(findings) == 0


# ── Tests de detección de terminología (con mock) ───────────────────────────


@pytest.mark.asyncio
async def test_terminology_no_llm():
    """Sin LLM, terminology no debería ejecutarse."""
    from app.rag.inconsistencies import detect_terminology_issues

    chunks = [
        {
            "chroma_id": "chunk_a",
            "doc_id": "doc_1",
            "text": "El usuario debe registrarse",
            "content": "El usuario debe registrarse",
        },
        {
            "chroma_id": "chunk_b",
            "doc_id": "doc_2",
            "text": "El cliente debe registrarse",
            "content": "El cliente debe registrarse",
        },
    ]
    findings, term_map = await detect_terminology_issues(chunks)
    assert findings == []
    assert term_map == {}


# ── Tests de integración de detect_all_inconsistencies ──────────────────────


@pytest.mark.asyncio
async def test_detect_all_no_llm():
    """detect_all_inconsistencies sin LLM solo ejecuta numerical y structural."""
    chunks = [
        {
            "chroma_id": "chunk_a",
            "doc_id": "doc_1",
            "text": "El curso dura 40 horas en total",
            "content": "El curso dura 40 horas en total",
        },
        {
            "chroma_id": "chunk_b",
            "doc_id": "doc_1",
            "text": "## Introducción\n\nTexto sin h1",
            "content": "## Introducción\n\nTexto sin h1",
        },
    ]
    findings, term_map = await detect_all_inconsistencies(
        chunks=chunks,
        terminology_map=None,
        enable_llm=False,
    )
    assert isinstance(findings, list)
    assert isinstance(term_map, dict)
    # Sin LLM, no debería haber self_contradiction ni terminology
    for f in findings:
        assert f["type"] in ("numerical", "structural")


@pytest.mark.asyncio
async def test_detect_all_empty_chunks():
    """Chunks vacíos no deberían causar errores."""
    findings, term_map = await detect_all_inconsistencies(
        chunks=[],
        terminology_map=None,
        enable_llm=False,
    )
    assert findings == []


@pytest.mark.asyncio
async def test_detect_all_with_terminology_map():
    """Probar que el terminology_map se propaga correctamente."""
    chunks = [
        {
            "chroma_id": "chunk_a",
            "doc_id": "doc_1",
            "text": "Contenido del curso",
            "content": "Contenido del curso",
        },
    ]
    existing_map = {"doc_1": [{"term": "test", "definition": "def", "context": "ctx"}]}
    findings, term_map = await detect_all_inconsistencies(
        chunks=chunks,
        terminology_map=existing_map,
        enable_llm=False,
    )
    # El mapa existente no debería perderse
    assert "doc_1" in term_map
    assert term_map["doc_1"][0]["term"] == "test"


# ── Tests de validación de campos en findings ──────────────────────────────


class TestInconsistencyFindingStructure:
    def test_required_fields_present(self):
        """Verifica que todos los hallazgos tengan los campos requeridos."""
        chunks = [
            {
                "chroma_id": "chunk_a",
                "doc_id": "doc_1",
                "text": "El curso dura 40 horas",
                "content": "El curso dura 40 horas",
            },
            {
                "chroma_id": "chunk_b",
                "doc_id": "doc_1",
                "text": "El curso dura 120 horas",
                "content": "El curso dura 120 horas",
            },
        ]
        findings = detect_numerical_inconsistencies(chunks)
        for f in findings:
            assert "type" in f
            assert f["type"] in (
                "self_contradiction",
                "terminology",
                "numerical",
                "structural",
            )
            assert "severity" in f
            assert f["severity"] in ("high", "medium", "low")
            assert "doc_id_a" in f
            assert "extract_a" in f
            assert "description" in f
            assert "suggestion" in f
            # Validar tipos
            assert isinstance(f["description"], str)
            assert isinstance(f["suggestion"], str)
