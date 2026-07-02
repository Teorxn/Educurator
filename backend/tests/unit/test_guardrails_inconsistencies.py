"""
Tests para #60 — Validación de guardrails de detect_inconsistencies.

Verifica:
  - DetectInconsistenciesSuccess schema
  - DetectInconsistenciesError schema
  - InconsistencyFinding valid/invalid
  - validate_inconsistency_finding
  - TOOL_OUTPUT_SCHEMAS registro
"""

import pytest
from app.tools.guardrails import (
    TOOL_OUTPUT_SCHEMAS,
    DetectInconsistenciesError,
    DetectInconsistenciesSuccess,
    SuggestionDataValidationError,
    validate_inconsistency_finding,
    validate_tool_output,
)
from pydantic import ValidationError


class TestDetectInconsistenciesSchemas:
    """Test de los modelos Pydantic para detect_inconsistencies."""

    def test_success_valid(self):
        data = {
            "status": "success",
            "findings": [
                {
                    "type": "numerical",
                    "severity": "high",
                    "chunk_id_a": "chunk_1",
                    "chunk_id_b": "chunk_2",
                    "doc_id_a": "doc_1",
                    "doc_id_b": "doc_1",
                    "extract_a": "40 horas",
                    "extract_b": "120 horas",
                    "description": "Valores contradictorios en horas",
                    "suggestion": "Unificar valores",
                }
            ],
            "total": 1,
            "llm_used": False,
        }
        model = DetectInconsistenciesSuccess.model_validate(data)
        assert model.status == "success"
        assert model.total == 1
        assert len(model.findings) == 1
        assert model.llm_used is False

    def test_success_no_findings(self):
        data = {
            "status": "success",
            "findings": [],
            "total": 0,
            "llm_used": False,
        }
        model = DetectInconsistenciesSuccess.model_validate(data)
        assert model.total == 0
        assert model.findings == []

    def test_success_with_llm(self):
        data = {
            "status": "success",
            "findings": [],
            "total": 0,
            "llm_used": True,
        }
        model = DetectInconsistenciesSuccess.model_validate(data)
        assert model.llm_used is True

    def test_success_invalid_type(self):
        """Tipo de inconsistencia inválido debe fallar."""
        data = {
            "status": "success",
            "findings": [
                {
                    "type": "invalid_type",
                    "severity": "high",
                    "chunk_id_a": "chunk_1",
                    "chunk_id_b": "",
                    "doc_id_a": "doc_1",
                    "doc_id_b": "",
                    "extract_a": "texto",
                    "extract_b": "",
                    "description": "Test",
                    "suggestion": "Test",
                }
            ],
            "total": 1,
            "llm_used": False,
        }
        with pytest.raises(ValidationError):
            DetectInconsistenciesSuccess.model_validate(data)

    def test_success_invalid_severity(self):
        """Severidad inválida debe fallar."""
        data = {
            "status": "success",
            "findings": [
                {
                    "type": "numerical",
                    "severity": "critical",
                    "chunk_id_a": "chunk_1",
                    "chunk_id_b": "",
                    "doc_id_a": "doc_1",
                    "doc_id_b": "",
                    "extract_a": "texto",
                    "extract_b": "",
                    "description": "Test",
                    "suggestion": "Test",
                }
            ],
            "total": 1,
            "llm_used": False,
        }
        with pytest.raises(ValidationError):
            DetectInconsistenciesSuccess.model_validate(data)

    def test_success_missing_required_fields(self):
        """Campos requeridos faltantes deben fallar."""
        data = {
            "status": "success",
            "findings": [
                {
                    "type": "numerical",
                    "severity": "high",
                    # chunk_id_a es requerido
                    "chunk_id_a": "",
                    "chunk_id_b": "",
                    "doc_id_a": "doc_1",
                    "doc_id_b": "",
                    "extract_a": "",
                    "extract_b": "",
                    "description": "",
                    "suggestion": "",
                }
            ],
            "total": 1,
            "llm_used": False,
        }
        with pytest.raises(ValidationError):
            DetectInconsistenciesSuccess.model_validate(data)

    def test_error_valid(self):
        data = {
            "status": "error",
            "error": "Error de prueba",
            "findings": [],
        }
        model = DetectInconsistenciesError.model_validate(data)
        assert model.status == "error"
        assert model.error == "Error de prueba"

    def test_strict_extra_fields(self):
        """Campos extra deben ser rechazados (extra='forbid')."""
        data = {
            "status": "success",
            "findings": [],
            "total": 0,
            "llm_used": False,
            "extra_field": "no permitido",
        }
        with pytest.raises(ValidationError):
            DetectInconsistenciesSuccess.model_validate(data)


class TestValidateInconsistencyFinding:
    def test_valid_finding(self):
        finding = {
            "type": "self_contradiction",
            "severity": "high",
            "chunk_id_a": "chunk_1",
            "chunk_id_b": "chunk_2",
            "doc_id_a": "doc_1",
            "doc_id_b": "doc_1",
            "extract_a": "El límite es 30",
            "extract_b": "El límite es 50",
            "description": "Auto-contradicción detectada",
            "suggestion": "Unificar los valores",
        }
        result = validate_inconsistency_finding(finding)
        assert result["type"] == "self_contradiction"

    def test_valid_finding_terminology(self):
        finding = {
            "type": "terminology",
            "severity": "medium",
            "chunk_id_a": "",
            "chunk_id_b": "",
            "doc_id_a": "doc_1",
            "doc_id_b": "doc_2",
            "extract_a": "usuario: persona que usa el sistema",
            "extract_b": "cliente: persona que usa el sistema",
            "description": "Términos diferentes para mismo concepto",
            "suggestion": "Unificar terminología",
        }
        result = validate_inconsistency_finding(finding)
        assert result["type"] == "terminology"

    def test_valid_finding_structural(self):
        finding = {
            "type": "structural",
            "severity": "low",
            "chunk_id_a": "",
            "chunk_id_b": "",
            "doc_id_a": "doc_1",
            "doc_id_b": "doc_1",
            "extract_a": "Salto de nivel de encabezado",
            "extract_b": "",
            "description": "Inconsistencia estructural",
            "suggestion": "Corregir encabezados",
        }
        result = validate_inconsistency_finding(finding)
        assert result["type"] == "structural"

    def test_invalid_type(self):
        finding = {
            "type": "invalid_type",
            "severity": "high",
            "chunk_id_a": "chunk_1",
            "chunk_id_b": "",
            "doc_id_a": "doc_1",
            "doc_id_b": "",
            "extract_a": "test",
            "extract_b": "",
            "description": "test",
            "suggestion": "test",
        }
        with pytest.raises(SuggestionDataValidationError):
            validate_inconsistency_finding(finding)

    def test_invalid_severity(self):
        finding = {
            "type": "numerical",
            "severity": "critical",
            "chunk_id_a": "chunk_1",
            "chunk_id_b": "",
            "doc_id_a": "doc_1",
            "doc_id_b": "",
            "extract_a": "test",
            "extract_b": "",
            "description": "test",
            "suggestion": "test",
        }
        with pytest.raises(SuggestionDataValidationError):
            validate_inconsistency_finding(finding)

    def test_missing_required_fields(self):
        finding = {
            "type": "numerical",
            "severity": "high",
            # doc_id_a faltante
            "chunk_id_a": "chunk_1",
            "chunk_id_b": "",
            "doc_id_a": "",
            "doc_id_b": "",
            "extract_a": "test",
            "extract_b": "",
            "description": "test",
            "suggestion": "test",
        }
        with pytest.raises(SuggestionDataValidationError):
            validate_inconsistency_finding(finding)

    def test_extra_field_rejected(self):
        finding = {
            "type": "numerical",
            "severity": "high",
            "chunk_id_a": "chunk_1",
            "chunk_id_b": "",
            "doc_id_a": "doc_1",
            "doc_id_b": "",
            "extract_a": "test",
            "extract_b": "",
            "description": "test",
            "suggestion": "test",
            "extra_field": "no permitido",
        }
        with pytest.raises(SuggestionDataValidationError):
            validate_inconsistency_finding(finding)


class TestSchemaRegistered:
    def test_detect_inconsistencies_registered(self):
        assert "detect_inconsistencies" in TOOL_OUTPUT_SCHEMAS

    def test_validate_tool_output_success(self):
        data = {
            "status": "success",
            "findings": [],
            "total": 0,
            "llm_used": False,
        }
        result = validate_tool_output("detect_inconsistencies", data)
        assert result["status"] == "success"

    def test_validate_tool_output_error(self):
        data = {
            "status": "error",
            "error": "Error de prueba",
            "findings": [],
        }
        result = validate_tool_output("detect_inconsistencies", data)
        assert result["status"] == "error"
