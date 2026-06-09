"""
#18 — Guardrails: JSON schema estricto en tools del agente.

Define los schemas de output para cada tool y provee validación
antes de retornar resultados al grafo LangGraph.

Schemas en formato JSON Schema (draft-07) para usar con jsonschema.
"""

import logging
from typing import Any, Dict

from jsonschema import ValidationError
from jsonschema import validate as jsonschema_validate

logger = logging.getLogger(__name__)


class ToolOutputValidationError(Exception):
    """Excepción lanzada cuando el output de una tool no pasa la validación."""

    pass


# ── JSON Schemas para cada tool ──────────────────────────────────────────────

# Tool 1: search_documents
_search_documents_success = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["success"]},
        "query": {"type": "string"},
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "chunk_id": {"type": "string"},
                    "content": {"type": "string"},
                    "similarity": {"type": "number"},
                    "metadata": {
                        "type": "object",
                        "properties": {
                            "doc_id": {"type": "string"},
                            "chunk_index": {"type": "integer"},
                            "token_count": {"type": "integer"},
                        },
                        "required": ["doc_id", "chunk_index", "token_count"],
                    },
                },
                "required": ["chunk_id", "content", "similarity", "metadata"],
            },
        },
        "total": {"type": "integer"},
    },
    "required": ["status", "query", "results", "total"],
}

_search_documents_error = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["error"]},
        "error": {"type": "string"},
        "results": {"type": "array"},
    },
    "required": ["status", "error"],
}

SCHEMA_SEARCH_DOCUMENTS = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "SearchDocumentsOutput",
    "description": "Output schema for search_documents tool",
    "oneOf": [_search_documents_success, _search_documents_error],
}

# Tool 2: compare_content
_compare_content_success = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["success"]},
        "chunk_a": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "preview": {"type": "string"},
                "doc_id": {"type": "string"},
                "chunk_index": {"type": "integer"},
            },
            "required": ["id", "preview", "doc_id", "chunk_index"],
        },
        "chunk_b": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "preview": {"type": "string"},
                "doc_id": {"type": "string"},
                "chunk_index": {"type": "integer"},
            },
            "required": ["id", "preview", "doc_id", "chunk_index"],
        },
        "similarity": {"type": "number"},
        "differences": {
            "type": "object",
            "properties": {
                "only_in_a": {"type": "array", "items": {"type": "string"}},
                "only_in_b": {"type": "array", "items": {"type": "string"}},
                "total_tokens_a": {"type": "integer"},
                "total_tokens_b": {"type": "integer"},
            },
            "required": ["only_in_a", "only_in_b", "total_tokens_a", "total_tokens_b"],
        },
    },
    "required": ["status", "chunk_a", "chunk_b", "similarity", "differences"],
}

_compare_content_error = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["error"]},
        "error": {"type": "string"},
    },
    "required": ["status", "error"],
}

SCHEMA_COMPARE_CONTENT = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "CompareContentOutput",
    "description": "Output schema for compare_content tool",
    "oneOf": [_compare_content_success, _compare_content_error],
}

# Tool 3: detect_conflict
_detect_conflict_success = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["success"]},
        "doc_a": {"type": "string"},
        "doc_b": {"type": "string"},
        "total_chunks_a": {"type": "integer"},
        "total_chunks_b": {"type": "integer"},
        "comparisons": {"type": "integer"},
        "conflicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "chunk_a_id": {"type": "string"},
                    "chunk_b_id": {"type": "string"},
                    "similarity": {"type": "number"},
                    "content_a_preview": {"type": "string"},
                    "content_b_preview": {"type": "string"},
                    "index_a": {"type": "integer"},
                },
                "required": [
                    "chunk_a_id",
                    "chunk_b_id",
                    "similarity",
                    "content_a_preview",
                    "content_b_preview",
                    "index_a",
                ],
            },
        },
        "conflict_count": {"type": "integer"},
    },
    "required": [
        "status",
        "doc_a",
        "doc_b",
        "total_chunks_a",
        "total_chunks_b",
        "comparisons",
        "conflicts",
        "conflict_count",
    ],
}

_detect_conflict_error = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["error"]},
        "error": {"type": "string"},
    },
    "required": ["status", "error"],
}

SCHEMA_DETECT_CONFLICT = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "DetectConflictOutput",
    "description": "Output schema for detect_conflict tool",
    "oneOf": [_detect_conflict_success, _detect_conflict_error],
}

# Tool 4: suggest_update
_suggest_update_success = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["success"]},
        "suggestion_id": {"type": "string"},
        "document_id": {"type": "string"},
        "type": {"type": "string"},
        "state": {"type": "string", "enum": ["pending"]},
        "source_doc_id": {"type": "string", "minLength": 1},
        "source_chunk_ids": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "confidence_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "message": {"type": "string"},
    },
    "required": [
        "status",
        "suggestion_id",
        "document_id",
        "type",
        "state",
        "source_doc_id",
        "source_chunk_ids",
        "confidence_score",
        "message",
    ],
}

_suggest_update_error = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["error"]},
        "error": {"type": "string"},
    },
    "required": ["status", "error"],
}

SCHEMA_SUGGEST_UPDATE = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "SuggestUpdateOutput",
    "description": "Output schema for suggest_update tool",
    "oneOf": [_suggest_update_success, _suggest_update_error],
}

# Tool 5: generate_faq_entry
_generate_faq_success = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["success"]},
        "faq": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "answer": {"type": "string"},
                "source_chunk_id": {"type": "string"},
                "topic": {"type": "string"},
            },
            "required": ["question", "answer", "source_chunk_id", "topic"],
        },
    },
    "required": ["status", "faq"],
}

_generate_faq_error = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["error"]},
        "error": {"type": "string"},
    },
    "required": ["status", "error"],
}

SCHEMA_GENERATE_FAQ = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "GenerateFaqEntryOutput",
    "description": "Output schema for generate_faq_entry tool",
    "oneOf": [_generate_faq_success, _generate_faq_error],
}

# Tool 6: log_action
_log_action_logged = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["logged"]},
        "audit_log_id": {"type": "string"},
        "document_id": {"type": ["string", "null"]},
        "action": {"type": "string"},
        "detail": {"type": "string"},
        "agent_step": {"type": "string"},
        "timestamp": {"type": "string"},
        "context": {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "detail": {"type": "string"},
                "agent_step": {"type": "string"},
                "source": {"type": "string", "enum": ["agent_tool"]},
            },
            "required": ["action", "detail", "agent_step", "source"],
        },
        "message": {"type": "string"},
    },
    "required": [
        "status",
        "audit_log_id",
        "document_id",
        "action",
        "detail",
        "agent_step",
        "timestamp",
        "context",
        "message",
    ],
}

_log_action_error = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["error"]},
        "action": {"type": "string"},
        "detail": {"type": "string"},
        "agent_step": {"type": "string"},
        "error": {"type": "string"},
    },
    "required": ["status", "error"],
}

SCHEMA_LOG_ACTION = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "LogActionOutput",
    "description": "Output schema for log_action tool",
    "oneOf": [_log_action_logged, _log_action_error],
}

# Tool 7: detect_redundancy
_detect_redundancy_success = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["success"]},
        "query_chunk_id": {"type": "string"},
        "threshold": {"type": "number"},
        "total_comparisons": {"type": "integer"},
        "redundant_pairs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "chunk_id_a": {"type": "string"},
                    "chunk_id_b": {"type": "string"},
                    "similarity": {"type": "number"},
                    "confidence_score": {"type": "number"},
                    "doc_id_a": {"type": "string"},
                    "doc_id_b": {"type": "string"},
                    "content_a_preview": {"type": "string"},
                    "content_b_preview": {"type": "string"},
                },
                "required": [
                    "chunk_id_a",
                    "chunk_id_b",
                    "similarity",
                    "confidence_score",
                    "doc_id_a",
                    "doc_id_b",
                    "content_a_preview",
                    "content_b_preview",
                ],
            },
        },
        "pair_count": {"type": "integer"},
    },
    "required": [
        "status",
        "query_chunk_id",
        "threshold",
        "total_comparisons",
        "redundant_pairs",
        "pair_count",
    ],
}

_detect_redundancy_error = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["error"]},
        "error": {"type": "string"},
        "redundant_pairs": {"type": "array"},
    },
    "required": ["status", "error"],
}

SCHEMA_DETECT_REDUNDANCY = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "DetectRedundancyOutput",
    "description": "Output schema for detect_redundancy tool",
    "oneOf": [_detect_redundancy_success, _detect_redundancy_error],
}

# ── Registry ──────────────────────────────────────────────────────────────────


def _make_schema_strict(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Marca recursivamente los objetos JSON Schema como cerrados.

    Esto evita que una tool retorne campos no declarados y mantiene la validación
    en modo estricto para outputs success y error.
    """
    if schema.get("type") == "object":
        schema.setdefault("additionalProperties", False)
        for subschema in schema.get("properties", {}).values():
            if isinstance(subschema, dict):
                _make_schema_strict(subschema)
    for key in ("items", "additionalProperties"):
        subschema = schema.get(key)
        if isinstance(subschema, dict):
            _make_schema_strict(subschema)
    for key in ("oneOf", "anyOf", "allOf"):
        for subschema in schema.get(key, []):
            if isinstance(subschema, dict):
                _make_schema_strict(subschema)
    return schema


TOOL_OUTPUT_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "search_documents": SCHEMA_SEARCH_DOCUMENTS,
    "compare_content": SCHEMA_COMPARE_CONTENT,
    "detect_conflict": SCHEMA_DETECT_CONFLICT,
    "suggest_update": SCHEMA_SUGGEST_UPDATE,
    "generate_faq_entry": SCHEMA_GENERATE_FAQ,
    "log_action": SCHEMA_LOG_ACTION,
    "detect_redundancy": SCHEMA_DETECT_REDUNDANCY,
}

for _schema in TOOL_OUTPUT_SCHEMAS.values():
    _make_schema_strict(_schema)

# ── Validación ────────────────────────────────────────────────────────────────


def validate_tool_output(tool_name: str, output: dict) -> dict:
    """Valida el output de una tool contra su schema JSON.

    Args:
        tool_name: Nombre de la tool (clave en TOOL_OUTPUT_SCHEMAS).
        output: Diccionario con el output de la tool a validar.

    Returns:
        El mismo diccionario si pasa la validación.

    Raises:
        ToolOutputValidationError: Si el output no cumple el schema.
        KeyError: Si el tool_name no existe en TOOL_OUTPUT_SCHEMAS.
    """
    if tool_name not in TOOL_OUTPUT_SCHEMAS:
        raise KeyError(
            f"Tool '{tool_name}' no registrada en TOOL_OUTPUT_SCHEMAS. "
            f"Disponibles: {list(TOOL_OUTPUT_SCHEMAS.keys())}"
        )

    schema = TOOL_OUTPUT_SCHEMAS[tool_name]

    try:
        jsonschema_validate(output, schema)
    except ValidationError as e:
        logger.error(
            "❌ Validación fallida para tool '%s': %s\nOutput: %s",
            tool_name,
            e.message,
            output,
        )
        raise ToolOutputValidationError(
            f"Output de '{tool_name}' no pasa validación: {e.message}"
        ) from e

    return output
