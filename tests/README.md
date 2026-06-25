# Tests del Proyecto EduCurator

Este documento describe los tests del sistema agéntico de curación de contenido, cómo ejecutarlos y qué cubre cada uno.

---

## Índice

1. [Estructura de tests](#1-estructura-de-tests)
2. [Requisitos](#2-requisitos)
3. [Cómo ejecutar los tests](#3-cómo-ejecutar-los-tests)
4. [Tests de unidad de redundancia](#4-tests-de-unidad-de-redundancia)
5. [Tests de guardrails (schemas de tools)](#5-tests-de-guardrails)
6. [Tests de integración del pipeline del agente](#6-tests-de-integración-del-pipeline-del-agente)
7. [Añadir nuevos tests](#7-añadir-nuevos-tests)

---

## 1. Estructura de tests

```
Educurator/
├── tests/                              # Tests de alto nivel (redundancia)
│   ├── __init__.py
│   └── test_redundancy.py              # Algoritmo de detección de redundancia
│
├── backend/
│   ├── pytest.ini                      # Configuración de pytest (asyncio_mode = auto)
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── test_guardrails.py          # Validación JSON Schema de tools del agente
│   │   └── test_agent_pipeline.py      # Pipeline completo del agente (nodos + flujo)
│   └── ...
```

| Archivo | Tipo | Dependencias externas |
|---|---|---|
| `tests/test_redundancy.py` | Unitario | Ninguna (todo mockeado) |
| `backend/tests/test_guardrails.py` | Unitario | Ninguna |
| `backend/tests/test_agent_pipeline.py` | Integración | Mockea DB, ChromaDB y filesystem |

---

## 2. Requisitos

### Python

Los tests usan `pytest` y `pytest-asyncio`. Ya están instalados en el `.venv`:

```sh
cd backend
python -m pip install pytest pytest-asyncio
```

### Configuración de pytest

El archivo `backend/pytest.ini` configura el modo asyncio automático:

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

Esto permite que las funciones `async def` se ejecuten directamente como tests sin necesidad del decorador `@pytest.mark.asyncio`.

---

## 3. Cómo ejecutar los tests

### Todos los tests del proyecto

```sh
# Desde la raíz del proyecto
pytest tests/ backend/tests/ -v
```

### Tests específicos

```sh
# Solo tests de redundancia
pytest tests/test_redundancy.py -v

# Solo tests de guardrails
pytest backend/tests/test_guardrails.py -v

# Solo tests del pipeline del agente
pytest backend/tests/test_agent_pipeline.py -v
```

### Con cobertura

```sh
pytest tests/ backend/tests/ --cov=app --cov-report=term-missing
```

### Tests de integración real (requieren base de datos)

Algunos tests se saltan automáticamente si no se define la variable `INTEGRATION_TESTS`. Para ejecutarlos:

```sh
# Windows (PowerShell)
$env:INTEGRATION_TESTS=1
pytest backend/tests/test_agent_pipeline.py::TestFullPipeline::test_run_curation_with_no_documents -v

# Linux/Mac
INTEGRATION_TESTS=1 pytest backend/tests/test_agent_pipeline.py::TestFullPipeline::test_run_curation_with_no_documents -v
```

Requiere tener PostgreSQL y ChromaDB funcionando (vía Docker o local).

---

## 4. Tests de unidad de redundancia

**Archivo:** `tests/test_redundancy.py`

Cubre el algoritmo de detección de redundancia (`app.rag.redundancy`):

### `TestCosineSimilarity`
| Test | Descripción |
|---|---|
| `test_identical_vectors` | Vectores idénticos → similitud = 1.0 |
| `test_orthogonal_vectors` | Vectores ortogonales → similitud = 0.0 |
| `test_opposite_vectors` | Vectores opuestos → similitud = -1.0 |
| `test_zero_vector` | Vector cero → similitud = 0.0 (evita división por cero) |
| `test_partial_similarity` | Vectores parcialmente similares → 0.5 < resultado < 1.0 |
| `test_rounding` | Resultado redondeado a 4 decimales |

### `TestConfidenceScore`
| Test | Descripción |
|---|---|
| `test_perfect_confidence` | Similitud 1.0 + chunks largos + consistencia perfecta → score alto |
| `test_high_similarity_reduces_confidence` | Baja similitud reduce el score |
| `test_short_chunks_penalized` | Chunks cortos (< 20 tokens) penalizan el score |
| `test_score_range` | Score siempre entre 0.0 y 1.0 |
| `test_rounding_precision` | Score redondeado a 4 decimales |

### `TestRedundancyResultSchema` y `TestRedundancyReportSchema`
Validan que los modelos Pydantic acepten datos correctos y rechacen datos inválidos (similitud > 1.0, confidence fuera de rango, frozen model, etc.)

### `TestReportToJson`
Verifica la serialización a JSON del reporte de redundancia.

### `TestDetectRedundancy` (con FakeCollection)
Usa un `FakeCollection` que simula ChromaDB para probar la lógica de detección:

| Test | Descripción |
|---|---|
| `test_no_chunk_found` | Chunk inexistente → reporte vacío |
| `test_no_other_chunks` | Único chunk en colección → sin pares |
| `test_identical_chunks_detected` | Chunks idénticos → detectados como redundantes |
| `test_below_threshold_not_reported` | Similitud baja → no se reporta |
| `test_threshold_configurable` | Umbral personalizado funciona |
| `test_confidence_score_included` | Cada par incluye confidence_score |
| `test_same_doc_exclusion` | `include_same_doc=False` excluye pares del mismo doc |
| `test_max_pairs_limit` | `max_pairs` limita resultados |

### `TestDetectRedundancyBulk`
Verifica que `detect_redundancy_bulk` consolida pares sin duplicados (A-B y B-A).

### `TestRedundancyThresholdConfig`
Verifica el valor por defecto del threshold (`REDUNDANCY_THRESHOLD = 0.90`).

---

## 5. Tests de guardrails

**Archivo:** `backend/tests/test_guardrails.py`

Cubre la validación JSON Schema de las 7 tools del agente (`app.tools.guardrails`):

### `TestSchemasRegistered`
| Test | Descripción |
|---|---|
| `test_all_tools_registered` | Las 7 tools están en `TOOL_OUTPUT_SCHEMAS` |
| `test_each_schema_has_title` | Cada schema tiene campo `title` |
| `test_each_schema_has_oneOf` | Cada schema tiene variante success + error |

### Tests por tool

| Test class | Tool | Casos |
|---|---|---|
| `TestSearchDocuments` | `search_documents` | success con resultados, empty results, error, status inválido, metadata faltante |
| `TestCompareContent` | `compare_content` | success, error |
| `TestDetectConflict` | `detect_conflict` | success con conflictos, sin conflictos, error |
| `TestSuggestUpdate` | `suggest_update` | success, estado inválido, error |
| `TestGenerateFaqEntry` | `generate_faq_entry` | success, error |
| `TestLogAction` | `log_action` | logged con agent_step, sin persistencia (inválido), error, sin message |
| `TestDetectRedundancy` | `detect_redundancy` | success, sin pares, error, confidence faltante |

### `TestStrictSchemas`
Verifica que campos extra (no declarados en el schema) son rechazados gracias a `additionalProperties: false`.

### `TestUnknownTool`
Verifica que una tool no registrada lanza `KeyError`.

### `TestSuggestionRequiredFields`
Validación específica de los campos obligatorios de `suggest_update`:

| Test | Descripción |
|---|---|
| `test_all_required_fields_present` | Objeto completo pasa validación |
| `test_missing_source_doc_id` | `source_doc_id` ausente → error |
| `test_missing_confidence_score` | `confidence_score` ausente → error |
| `test_missing_source_chunk_ids` | `source_chunk_ids` ausente → error |
| `test_confidence_score_out_of_range_high` | Score > 1.0 → error |
| `test_confidence_score_out_of_range_low` | Score < 0.0 → error |
| `test_confidence_score_wrong_type` | Score no numérico → error |
| `test_source_doc_id_empty_string` | `source_doc_id` vacío → error |
| `test_source_chunk_ids_not_a_list` | `source_chunk_ids` no es lista → error |

---

## 6. Tests de integración del pipeline del agente

**Archivo:** `backend/tests/test_agent_pipeline.py`

Cubre el pipeline completo del agente LangGraph (nodos del grafo). Mockea PostgreSQL, ChromaDB y el filesystem.

### `TestGraphInfo`

Verifica que el grafo se compila correctamente y expone metadatos:

- **Nodos esperados**: `load_documents`, `chunk_and_embed`, `redundancy_detection`, `generate_suggestions`, `wait_human_approval`
- **7 tools registradas**: `search_documents`, `compare_content`, `detect_conflict`, `detect_redundancy`, `suggest_update`, `generate_faq_entry`, `log_action`

### `TestLoadDocumentsNode`

Mockea `AsyncSessionLocal` para simular PostgreSQL:

| Test | Descripción |
|---|---|
| `test_loads_pending_documents` | Carga documentos `needs_review`, los marca como `processing`, hace commit |
| `test_no_pending_documents` | Sin documentos pendientes → lista vacía, sin error |

### `TestChunkAndEmbedNode`

Mockea `parse_document`, `embed_chunks` y `Path.exists`:

| Test | Descripción |
|---|---|
| `test_processes_documents_successfully` | 2 documentos → 10 chunks (5 c/u), texts en state, sin error |
| `test_no_documents_to_process` | Sin `document_ids` → chunks vacío, sin commit |

### `TestRedundancyDetectionNode`

Mockea `detect_redundancy_bulk`:

| Test | Descripción |
|---|---|
| `test_detects_redundant_pairs` | Chunks con pares → findings con similarity y confidence_score |
| `test_no_chunks_no_findings` | Sin chunks → findings vacío |

### `TestGenerateSuggestionsNode`

Mockea `AsyncSessionLocal` y verifica la creación de sugerencias en Postgres:

| Test | Descripción |
|---|---|
| `test_creates_suggestions_from_redundancy_findings` | Findings → sugerencias `Suggestion` con tipo `redundancy`, status `pending`, confidence correcto |
| `test_creates_suggestions_from_tool_calls` | Mensajes del agente con `suggest_update` → sugerencias creadas |
| `test_no_suggestions_when_no_findings` | Sin findings ni tool calls → 0 sugerencias |

### `TestWaitHumanApprovalNode`

| Test | Descripción |
|---|---|
| `test_changes_documents_to_needs_review` | Documentos `processing` → `needs_review`, crea `DocumentHistory` con audit trail |

### `TestFullPipeline`

| Test | Descripción |
|---|---|
| `test_full_pipeline_execution` | Grafo mockeado: `run_curation()` retorna estado completo sin errores |
| `test_run_curation_with_no_documents` | **SKIP sin `INTEGRATION_TESTS=1`**. Pipeline real sin documentos se completa sin errores |

### `TestSuggestionPersistence`

| Test | Descripción |
|---|---|
| `test_suggestion_has_all_required_fields` | Toda sugerencia tiene `id`, `document_id`, `type`, `confidence_score` en rango |
| `test_rejects_invalid_confidence_score` | Score negativo (-0.5) se fija a 0.0 sin romper el pipeline |
| `test_skips_finding_without_chunk_ids` | Hallazgo sin chunk_ids se omite silenciosamente |

### `TestDocumentStateTransitions`

Tests simples de valores de enum:

| Test | Descripción |
|---|---|
| `test_initial_state_is_needs_review` | Documento nuevo → `needs_review` |
| `test_processing_transition` | `load_documents_node` → `processing` |
| `test_back_to_needs_review` | `wait_human_approval_node` → `needs_review` |
| `test_valid_status_enum_values` | `DocumentStatus` tiene 5 valores exactos |
| `test_valid_suggestion_statuses` | `SuggestionStatus` tiene pending, approved, rejected |
| `test_valid_suggestion_types` | `SuggestionType` tiene redundancy, conflict, faq, update |

### `TestAuditTrail`

| Test | Descripción |
|---|---|
| `test_agent_completion_creates_history` | `wait_human_approval_node` crea `DocumentHistory` con action `agent_completed`, before/after content |

---

## 7. Añadir nuevos tests

### Para un nuevo nodo del grafo

1. Crear la clase dentro de `Test<NombreNodo>` en `backend/tests/test_agent_pipeline.py`
2. Usar `@patch("app.agents.nodes.<dependencia>")` para mockear DB, ChromaDB o LLM
3. Usar `AsyncMock` para métodos asíncronos (`execute`, `commit`, `flush`)
4. Pasar el estado como `AgentState` (el TypedDict definido en `app.agents.state`)

### Para una nueva tool

Añadir tests en `backend/tests/test_guardrails.py`:
1. Registrar el schema en `TOOL_OUTPUT_SCHEMAS`
2. Crear clase con casos success y error
3. Verificar que `validate_tool_output` acepta/rechaza correctamente

### Para el algoritmo de redundancia

Añadir tests en `tests/test_redundancy.py`:
1. Usar `FakeCollection` (simula ChromaDB en memoria)
2. Crear chunks con `_make_chunk()` helper
3. Llamar a `detect_redundancy()` directamente

### Buenas prácticas

- **Mockear siempre** las dependencias externas (Postgres, ChromaDB, red, filesystem)
- Usar `MagicMock(spec=ClaseReal)` para obtener mocks con la interfaz correcta
- Para sesiones de base de datos, usar `AsyncMock(spec=AsyncSession)`
- Los tests deben ser **independientes** y **determinísticos**
- Preferir `@patch` con `autospec=True` cuando sea posible para detectar cambios de interfaz
- Incluir casos borde: valores vacíos, nulos, fuera de rango
