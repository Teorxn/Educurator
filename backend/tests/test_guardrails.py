"""
#18 — Tests: Guardrails con JSON schema estricto en tools del agente.

Valida que:
  1. Cada schema acepta outputs correctos (success y error)
  2. Outputs inválidos lanzan ToolOutputValidationError
  3. ToolOutputValidationError tiene el mensaje adecuado
  4. Todas las 7 tools están registradas en TOOL_OUTPUT_SCHEMAS
  5. Los requerimientos específicos (source_doc_id, confidence_score) se validan
"""

import pytest
from app.tools.guardrails import (
    TOOL_OUTPUT_SCHEMAS,
    SuggestionDataValidationError,
    ToolOutputValidationError,
    validate_redundancy_finding,
    validate_suggestion_data,
    validate_tool_output,
)


class TestSchemasRegistered:
    """Todas las 7 tools deben estar registradas."""

    def test_all_tools_registered(self):
        assert set(TOOL_OUTPUT_SCHEMAS.keys()) == {
            "search_documents",
            "compare_content",
            "detect_conflict",
            "suggest_update",
            "generate_faq_entry",
            "log_action",
            "detect_redundancy",
        }

    def test_each_schema_has_title(self):
        for name, schema in TOOL_OUTPUT_SCHEMAS.items():
            assert "title" in schema, f"{name} schema lacks title"

    def test_each_schema_has_oneOf(self):
        for name, schema in TOOL_OUTPUT_SCHEMAS.items():
            assert "oneOf" in schema, f"{name} schema lacks oneOf"
            assert len(schema["oneOf"]) >= 2, f"{name} should have at least 2 variants"


class TestSearchDocuments:
    """Validación del schema de search_documents."""

    TOOL = "search_documents"

    def test_valid_success(self):
        output = {
            "status": "success",
            "query": "algoritmos de búsqueda",
            "results": [
                {
                    "chunk_id": "chunk_001",
                    "content": "Los algoritmos de búsqueda binaria...",
                    "similarity": 0.95,
                    "metadata": {
                        "doc_id": "doc_abc",
                        "chunk_index": 2,
                        "token_count": 150,
                    },
                }
            ],
            "total": 1,
        }
        assert validate_tool_output(self.TOOL, output) == output

    def test_valid_empty_results(self):
        output = {
            "status": "success",
            "query": "consulta sin resultados",
            "results": [],
            "total": 0,
        }
        assert validate_tool_output(self.TOOL, output) == output

    def test_valid_error(self):
        output = {"status": "error", "error": "ChromaDB no disponible", "results": []}
        assert validate_tool_output(self.TOOL, output) == output

    def test_invalid_status(self):
        output = {"status": "invalid", "error": "test"}
        with pytest.raises(ToolOutputValidationError):
            validate_tool_output(self.TOOL, output)

    def test_missing_results_in_success(self):
        output = {"status": "success", "query": "test"}
        with pytest.raises(ToolOutputValidationError):
            validate_tool_output(self.TOOL, output)

    def test_result_missing_metadata_fields(self):
        output = {
            "status": "success",
            "results": [
                {
                    "chunk_id": "chunk_1",
                    "content": "test",
                    "similarity": 0.5,
                    "metadata": {},  # Falta doc_id, chunk_index, token_count
                }
            ],
        }
        with pytest.raises(ToolOutputValidationError):
            validate_tool_output(self.TOOL, output)


class TestCompareContent:
    """Validación del schema de compare_content."""

    TOOL = "compare_content"

    def test_valid_success(self):
        output = {
            "status": "success",
            "chunk_a": {
                "id": "chunk_a",
                "preview": "Contenido del primer chunk...",
                "doc_id": "doc_1",
                "chunk_index": 0,
            },
            "chunk_b": {
                "id": "chunk_b",
                "preview": "Contenido del segundo chunk...",
                "doc_id": "doc_2",
                "chunk_index": 1,
            },
            "similarity": 0.85,
            "differences": {
                "only_in_a": ["palabra1", "palabra2"],
                "only_in_b": ["palabra3"],
                "total_tokens_a": 100,
                "total_tokens_b": 120,
            },
        }
        assert validate_tool_output(self.TOOL, output) == output

    def test_valid_error(self):
        output = {"status": "error", "error": "Chunks no encontrados"}
        assert validate_tool_output(self.TOOL, output) == output


class TestDetectConflict:
    """Validación del schema de detect_conflict."""

    TOOL = "detect_conflict"

    def test_valid_success(self):
        output = {
            "status": "success",
            "doc_a": "doc_1",
            "doc_b": "doc_2",
            "total_chunks_a": 5,
            "total_chunks_b": 7,
            "comparisons": 35,
            "conflicts": [
                {
                    "chunk_a_id": "chunk_a1",
                    "chunk_b_id": "chunk_b1",
                    "similarity": 0.82,
                    "content_a_preview": "El costo es $100...",
                    "content_b_preview": "El costo es $150...",
                    "index_a": 0,
                }
            ],
            "conflict_count": 1,
        }
        assert validate_tool_output(self.TOOL, output) == output

    def test_no_conflicts(self):
        output = {
            "status": "success",
            "doc_a": "doc_1",
            "doc_b": "doc_2",
            "total_chunks_a": 3,
            "total_chunks_b": 3,
            "comparisons": 9,
            "conflicts": [],
            "conflict_count": 0,
        }
        assert validate_tool_output(self.TOOL, output) == output


class TestSuggestUpdate:
    """Validación del schema de suggest_update."""

    TOOL = "suggest_update"

    def test_valid_success(self):
        output = {
            "status": "success",
            "suggestion_id": "550e8400-e29b-41d4-a716-446655440000",
            "document_id": "doc_123",
            "type": "redundancy",
            "state": "pending",
            "source_doc_id": "doc_123",
            "source_chunk_ids": ["chunk_1"],
            "confidence_score": 0.91,
            "message": "Sugerencia creada correctamente.",
        }
        assert validate_tool_output(self.TOOL, output) == output

    def test_invalid_state(self):
        output = {
            "status": "success",
            "suggestion_id": "abc",
            "document_id": "doc_1",
            "type": "redundancy",
            "state": "approved",  # Debería ser "pending"
            "source_doc_id": "doc_1",
            "source_chunk_ids": ["chunk_1"],
            "confidence_score": 0.8,
            "message": "test",
        }
        with pytest.raises(ToolOutputValidationError):
            validate_tool_output(self.TOOL, output)

    def test_valid_error(self):
        output = {"status": "error", "error": "ID de documento inválido"}
        assert validate_tool_output(self.TOOL, output) == output


class TestGenerateFaqEntry:
    """Validación del schema de generate_faq_entry."""

    TOOL = "generate_faq_entry"

    def test_valid_success(self):
        output = {
            "status": "success",
            "faq": {
                "question": "¿Qué es un algoritmo de búsqueda?",
                "answer": "Un algoritmo que encuentra elementos...",
                "source_chunk_id": "chunk_001",
                "topic": "algoritmos",
            },
        }
        assert validate_tool_output(self.TOOL, output) == output

    def test_valid_error(self):
        output = {"status": "error", "error": "Contenido insuficiente"}
        assert validate_tool_output(self.TOOL, output) == output


class TestLogAction:
    """Validación del schema de log_action."""

    TOOL = "log_action"

    def test_valid_logged_with_agent_step(self):
        output = {
            "status": "logged",
            "audit_log_id": "550e8400-e29b-41d4-a716-446655440000",
            "document_id": None,
            "action": "search",
            "detail": "Búsqueda de algoritmo de ordenamiento",
            "agent_step": "step_1",
            "timestamp": "2026-06-08T10:00:00+00:00",
            "context": {
                "action": "search",
                "detail": "Búsqueda de algoritmo de ordenamiento",
                "agent_step": "step_1",
                "source": "agent_tool",
            },
            "message": "Acción 'search' registrada correctamente",
        }
        assert validate_tool_output(self.TOOL, output) == output

    def test_logged_without_persistence_fields_is_invalid(self):
        output = {
            "status": "logged",
            "action": "search",
            "detail": "detalle",
            "message": "Acción registrada en log (fallo DB: ...)",
        }
        with pytest.raises(ToolOutputValidationError):
            validate_tool_output(self.TOOL, output)

    def test_valid_error(self):
        output = {
            "status": "error",
            "action": "search",
            "detail": "detalle",
            "agent_step": "step_1",
            "error": "Error de conexión",
        }
        assert validate_tool_output(self.TOOL, output) == output

    def test_missing_message(self):
        output = {
            "status": "logged",
            "audit_log_id": "id",
            "document_id": None,
            "action": "search",
            "detail": "test",
            "agent_step": "step_1",
            "timestamp": "2026-06-08T10:00:00+00:00",
            "context": {
                "action": "search",
                "detail": "test",
                "agent_step": "step_1",
                "source": "agent_tool",
            },
        }
        with pytest.raises(ToolOutputValidationError):
            validate_tool_output(self.TOOL, output)


class TestStrictSchemas:
    """Los outputs no deben aceptar campos no declarados."""

    def test_extra_field_is_rejected(self):
        output = {
            "status": "success",
            "query": "test",
            "results": [],
            "total": 0,
            "unexpected": True,
        }
        with pytest.raises(ToolOutputValidationError):
            validate_tool_output("search_documents", output)


class TestDetectRedundancy:
    """Validación del schema de detect_redundancy."""

    TOOL = "detect_redundancy"

    def test_valid_success(self):
        output = {
            "status": "success",
            "query_chunk_id": "chunk_001",
            "threshold": 0.9,
            "total_comparisons": 50,
            "redundant_pairs": [
                {
                    "chunk_id_a": "chunk_001",
                    "chunk_id_b": "chunk_002",
                    "similarity": 0.95,
                    "confidence_score": 0.88,
                    "doc_id_a": "doc_1",
                    "doc_id_b": "doc_2",
                    "content_a_preview": "Primer contenido...",
                    "content_b_preview": "Segundo contenido...",
                }
            ],
            "pair_count": 1,
        }
        assert validate_tool_output(self.TOOL, output) == output

    def test_no_redundant_pairs(self):
        output = {
            "status": "success",
            "query_chunk_id": "chunk_001",
            "threshold": 0.9,
            "total_comparisons": 50,
            "redundant_pairs": [],
            "pair_count": 0,
        }
        assert validate_tool_output(self.TOOL, output) == output

    def test_valid_error(self):
        output = {
            "status": "error",
            "error": "Chunk no encontrado en ChromaDB",
            "redundant_pairs": [],
        }
        assert validate_tool_output(self.TOOL, output) == output

    def test_pair_missing_confidence(self):
        output = {
            "status": "success",
            "query_chunk_id": "chunk_001",
            "threshold": 0.9,
            "total_comparisons": 10,
            "redundant_pairs": [
                {
                    "chunk_id_a": "chunk_001",
                    "chunk_id_b": "chunk_002",
                    "similarity": 0.95,
                    # Falta confidence_score
                    "doc_id_a": "doc_1",
                    "doc_id_b": "doc_2",
                    "content_a_preview": "...",
                    "content_b_preview": "...",
                }
            ],
            "pair_count": 1,
        }
        with pytest.raises(ToolOutputValidationError):
            validate_tool_output(self.TOOL, output)


class TestUnknownTool:
    """Comportamiento con tools no registradas."""

    def test_unknown_tool_raises_key_error(self):
        with pytest.raises(KeyError):
            validate_tool_output("nonexistent_tool", {})


class TestSuggestionRequiredFields:
    """Valida que las sugerencias requieran source_doc_id y confidence_score.

    Usa validate_suggestion_data() de guardrails directamente,
    que es la función centralizada de validación de sugerencias.
    """

    def test_all_required_fields_present(self):
        args = {
            "source_doc_id": "doc_123",
            "confidence_score": 0.95,
            "source_chunk_ids": ["chunk_1", "chunk_2"],
        }
        # No debe lanzar excepción
        validate_suggestion_data(args)

    def test_missing_source_doc_id(self):
        args = {
            "confidence_score": 0.95,
            "source_chunk_ids": ["chunk_1"],
        }
        with pytest.raises(SuggestionDataValidationError) as exc:
            validate_suggestion_data(args)
        assert "source_doc_id" in str(exc.value)

    def test_missing_confidence_score(self):
        args = {
            "source_doc_id": "doc_123",
            "source_chunk_ids": ["chunk_1"],
        }
        with pytest.raises(SuggestionDataValidationError) as exc:
            validate_suggestion_data(args)
        assert "confidence_score" in str(exc.value)

    def test_missing_source_chunk_ids(self):
        args = {
            "source_doc_id": "doc_123",
            "confidence_score": 0.95,
        }
        with pytest.raises(SuggestionDataValidationError) as exc:
            validate_suggestion_data(args)
        assert "source_chunk_ids" in str(exc.value)

    def test_confidence_score_out_of_range_high(self):
        args = {
            "source_doc_id": "doc_123",
            "confidence_score": 1.5,
            "source_chunk_ids": ["chunk_1"],
        }
        with pytest.raises(SuggestionDataValidationError) as exc:
            validate_suggestion_data(args)
        assert "fuera de rango" in str(exc.value)

    def test_confidence_score_out_of_range_low(self):
        args = {
            "source_doc_id": "doc_123",
            "confidence_score": -0.1,
            "source_chunk_ids": ["chunk_1"],
        }
        with pytest.raises(SuggestionDataValidationError) as exc:
            validate_suggestion_data(args)
        assert "fuera de rango" in str(exc.value)

    def test_confidence_score_wrong_type(self):
        args = {
            "source_doc_id": "doc_123",
            "confidence_score": "alto",
            "source_chunk_ids": ["chunk_1"],
        }
        with pytest.raises(SuggestionDataValidationError) as exc:
            validate_suggestion_data(args)
        assert "confidence_score" in str(exc.value)

    def test_source_doc_id_empty_string(self):
        args = {
            "source_doc_id": "",
            "confidence_score": 0.95,
            "source_chunk_ids": ["chunk_1"],
        }
        with pytest.raises(SuggestionDataValidationError) as exc:
            validate_suggestion_data(args)
        assert "source_doc_id" in str(exc.value)

    def test_source_chunk_ids_not_a_list(self):
        args = {
            "source_doc_id": "doc_123",
            "confidence_score": 0.95,
            "source_chunk_ids": "chunk_1",
        }
        with pytest.raises(SuggestionDataValidationError) as exc:
            validate_suggestion_data(args)
        assert "source_chunk_ids" in str(exc.value)

    def test_source_chunk_ids_empty_list(self):
        args = {
            "source_doc_id": "doc_123",
            "confidence_score": 0.95,
            "source_chunk_ids": [],
        }
        with pytest.raises(SuggestionDataValidationError) as exc:
            validate_suggestion_data(args)
        assert "source_chunk_ids" in str(exc.value)


class TestValidateRedundancyFinding:
    """Valida la estructura de hallazgos de redundancia."""

    def test_valid_finding(self):
        finding = {
            "chunk_id_a": "chunk_a_1",
            "chunk_id_b": "chunk_b_1",
            "similarity": 0.95,
            "confidence_score": 0.85,
            "doc_id_a": "doc_a",
            "doc_id_b": "doc_b",
            "content_a_preview": "contenido del chunk a...",
            "content_b_preview": "contenido del chunk b...",
            "token_count_a": 100,
            "token_count_b": 150,
        }
        result = validate_redundancy_finding(finding)
        assert result is finding  # debe retornar el mismo dict

    def test_missing_required_fields(self):
        finding = {
            "chunk_id_a": "chunk_a_1",
            "similarity": 0.95,
        }
        with pytest.raises(SuggestionDataValidationError) as exc:
            validate_redundancy_finding(finding)
        assert "chunk_id_b" in str(exc.value)
        assert "confidence_score" in str(exc.value)
        assert "doc_id_a" in str(exc.value)

    def test_invalid_similarity_type(self):
        finding = {
            "chunk_id_a": "a",
            "chunk_id_b": "b",
            "similarity": "alta",
            "confidence_score": 0.8,
            "doc_id_a": "da",
            "doc_id_b": "db",
            "content_a_preview": "...",
            "content_b_preview": "...",
        }
        with pytest.raises(SuggestionDataValidationError) as exc:
            validate_redundancy_finding(finding)
        assert "similarity" in str(exc.value)


class TestMakeSchemaStrict:
    """Verifica que _make_schema_strict cierre correctamente los schemas."""

    def test_additional_properties_added_to_objects(self):
        """Los objetos deben tener additionalProperties=False después de strict."""
        from app.tools.guardrails import _make_schema_strict

        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
        }
        result = _make_schema_strict(schema)
        assert result["additionalProperties"] is False

    def test_nested_objects_in_items_are_closed(self):
        """Los objetos dentro de items de arrays deben cerrarse."""
        from app.tools.guardrails import _make_schema_strict

        schema = {
            "type": "object",
            "properties": {
                "items_list": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "nested": {
                                "type": "object",
                                "properties": {"value": {"type": "string"}},
                            },
                        },
                    },
                },
            },
        }
        result = _make_schema_strict(schema)
        items_schema = result["properties"]["items_list"]["items"]
        assert items_schema["additionalProperties"] is False
        assert items_schema["properties"]["nested"]["additionalProperties"] is False

    def test_one_of_subschemas_are_closed(self):
        """Los subschemas dentro de oneOf deben cerrarse."""
        from app.tools.guardrails import _make_schema_strict

        schema = {
            "oneOf": [
                {
                    "type": "object",
                    "properties": {"status": {"type": "string", "enum": ["ok"]}},
                },
                {
                    "type": "object",
                    "properties": {"status": {"type": "string", "enum": ["error"]}},
                },
            ],
        }
        result = _make_schema_strict(schema)
        for subschema in result["oneOf"]:
            assert subschema["additionalProperties"] is False
