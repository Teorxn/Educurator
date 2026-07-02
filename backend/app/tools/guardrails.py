"""
#18 — Guardrails: Validación Pydantic de outputs en tools del agente.

Define modelos Pydantic para cada tool y provee validación
antes de retornar resultados al grafo LangGraph.

Reemplaza la implementación anterior basada en JSON Schema/jsonschema
por modelos Pydantic con validación estricta (extra="forbid"),
aprovechando el sistema de tipos y validación que LangGraph ya utiliza.
"""

import logging
from typing import Annotated, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from pydantic import ValidationError as PydanticValidationError

logger = logging.getLogger(__name__)


class ToolOutputValidationError(Exception):
    """Excepción lanzada cuando el output de una tool no pasa la validación."""

    pass


class SuggestionDataValidationError(Exception):
    """Excepción lanzada cuando los datos de una sugerencia no pasan validación."""

    pass


__all__ = [
    "ToolOutputValidationError",
    "SuggestionDataValidationError",
    "validate_tool_output",
    "validate_suggestion_data",
    "validate_redundancy_finding",
    "validate_inconsistency_finding",
    "InconsistencyFinding",
    "DetectInconsistenciesSuccess",
    "DetectInconsistenciesError",
    "WebSearchResult",
    "SearchWebSuccess",
    "SearchWebError",
    "TOOL_OUTPUT_SCHEMAS",
]


# ═══════════════════════════════════════════════════════════════════════
# Modelos Pydantic para outputs de tools
# ═══════════════════════════════════════════════════════════════════════
# Cada tool define modelos Success y Error, combinados en una Union
# discriminada por el campo "status". Todos con extra="forbid" para
# no aceptar campos no declarados (equivalent to _make_schema_strict).
# ═══════════════════════════════════════════════════════════════════════


# ── Tool 1: search_documents ─────────────────────────────────────────


class _SearchResultMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str
    chunk_index: int
    token_count: int
    category: str | None = None


class _SearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    content: str
    similarity: float
    source_type: str | None = None
    metadata: _SearchResultMetadata


class SearchDocumentsSuccess(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success"]
    query: str
    results: List[_SearchResult]
    total: int


class SearchDocumentsError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["error"]
    error: str
    results: List = Field(default_factory=list)


# ── Tool 2: compare_content ──────────────────────────────────────────


class _ChunkInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    preview: str
    doc_id: str
    chunk_index: int


class _Differences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    only_in_a: List[str]
    only_in_b: List[str]
    total_tokens_a: int
    total_tokens_b: int


class CompareContentSuccess(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success"]
    chunk_a: _ChunkInfo
    chunk_b: _ChunkInfo
    similarity: float
    differences: _Differences


class CompareContentError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["error"]
    error: str


# ── Tool 3: detect_conflict ──────────────────────────────────────────


class _ConflictItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_a_id: str
    chunk_b_id: str
    similarity: float
    content_a_preview: str
    content_b_preview: str
    index_a: int


class DetectConflictSuccess(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success"]
    doc_a: str
    doc_b: str
    total_chunks_a: int
    total_chunks_b: int
    comparisons: int
    conflicts: List[_ConflictItem]
    conflict_count: int


class DetectConflictError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["error"]
    error: str


# ── Tool 4: suggest_update ───────────────────────────────────────────


class SuggestUpdateSuccess(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success"]
    suggestion_id: str
    document_id: str
    type: str
    state: Literal["pending"]
    source_doc_id: str = Field(min_length=1)
    source_chunk_ids: List[str] = Field(min_length=1)
    source_web_url: Optional[str] = None
    confidence_score: float = Field(ge=0.0, le=1.0)
    message: str


class SuggestUpdateError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["error"]
    error: str


# ── Tool 5: generate_faq_entry ───────────────────────────────────────


class _FaqContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    answer: str
    source_chunk_id: str
    topic: str


class GenerateFaqSuccess(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success"]
    faq: _FaqContent


class GenerateFaqError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["error"]
    error: str


# ── Tool 6: log_action ───────────────────────────────────────────────


class _LogContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    detail: str
    agent_step: str
    source: Literal["agent_tool"]


class LogActionSuccess(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["logged"]
    audit_log_id: str
    document_id: Optional[str] = None
    action: str
    detail: str
    agent_step: str
    timestamp: str
    context: _LogContext
    message: str


class LogActionError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["error"]
    action: str
    detail: str
    agent_step: str
    error: str


# ── Tool 8: detect_inconsistencies ────────────────────────────────────


class _InconsistencyFinding(BaseModel):
    """Hallazgo individual de inconsistencia."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["self_contradiction", "terminology", "numerical", "structural"]
    severity: Literal["high", "medium", "low"]
    chunk_id_a: str
    chunk_id_b: str = Field(default="", description="Vacío si es intra-chunk")
    doc_id_a: str
    doc_id_b: str = Field(
        default="", description="Mismo que doc_id_a si es intra-documento"
    )
    extract_a: str
    extract_b: str = Field(default="")
    description: str
    suggestion: str


class DetectInconsistenciesSuccess(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success"]
    findings: List[_InconsistencyFinding]
    total: int
    llm_used: bool


class DetectInconsistenciesError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["error"]
    error: str
    findings: List = Field(default_factory=list)


# ── Tool 7: detect_redundancy ────────────────────────────────────────


class _RedundantPair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id_a: str
    chunk_id_b: str
    similarity: float
    confidence_score: float
    doc_id_a: str
    doc_id_b: str
    content_a_preview: str
    content_b_preview: str


class WebSearchResult(BaseModel):
    """Resultado individual de búsqueda web."""

    model_config = ConfigDict(extra="forbid")

    title: str
    url: str
    snippet: str
    content: str
    source_type: Literal["web"]
    hash: str


class SearchWebSuccess(BaseModel):
    """Respuesta exitosa de búsqueda web."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["success"]
    query: str
    results: List[WebSearchResult]
    total: int
    provider: Literal["tavily", "duckduckgo"]


class SearchWebError(BaseModel):
    """Respuesta de error de búsqueda web."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["error"]
    error: str
    results: List = Field(default_factory=list)


class DetectRedundancySuccess(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success"]
    query_chunk_id: str
    threshold: float
    total_comparisons: int
    redundant_pairs: List[_RedundantPair]
    pair_count: int


class DetectRedundancyError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["error"]
    error: str
    redundant_pairs: List = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════════════════

# Usamos Annotated[Union[...], Field(discriminator="status")] para que
# Pydantic seleccione automáticamente el modelo Success/Error según
# el valor del campo "status" (discriminador nativo de Pydantic v2).

TOOL_OUTPUT_SCHEMAS: Dict[str, TypeAdapter] = {
    "search_documents": TypeAdapter(
        Annotated[
            Union[SearchDocumentsSuccess, SearchDocumentsError],
            Field(discriminator="status"),
        ]
    ),
    "compare_content": TypeAdapter(
        Annotated[
            Union[CompareContentSuccess, CompareContentError],
            Field(discriminator="status"),
        ]
    ),
    "detect_conflict": TypeAdapter(
        Annotated[
            Union[DetectConflictSuccess, DetectConflictError],
            Field(discriminator="status"),
        ]
    ),
    "suggest_update": TypeAdapter(
        Annotated[
            Union[SuggestUpdateSuccess, SuggestUpdateError],
            Field(discriminator="status"),
        ]
    ),
    "generate_faq_entry": TypeAdapter(
        Annotated[
            Union[GenerateFaqSuccess, GenerateFaqError],
            Field(discriminator="status"),
        ]
    ),
    "log_action": TypeAdapter(
        Annotated[
            Union[LogActionSuccess, LogActionError],
            Field(discriminator="status"),
        ]
    ),
    "search_web": TypeAdapter(
        Annotated[
            Union[SearchWebSuccess, SearchWebError],
            Field(discriminator="status"),
        ]
    ),
    "detect_redundancy": TypeAdapter(
        Annotated[
            Union[DetectRedundancySuccess, DetectRedundancyError],
            Field(discriminator="status"),
        ]
    ),
    "detect_inconsistencies": TypeAdapter(
        Annotated[
            Union[DetectInconsistenciesSuccess, DetectInconsistenciesError],
            Field(discriminator="status"),
        ]
    ),
}


# ═══════════════════════════════════════════════════════════════════════
# Validación de outputs de tools
# ═══════════════════════════════════════════════════════════════════════


def validate_tool_output(tool_name: str, output: dict) -> dict:
    """Valida el output de una tool contra su modelo Pydantic.

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

    adapter = TOOL_OUTPUT_SCHEMAS[tool_name]

    try:
        adapter.validate_python(output)
    except PydanticValidationError as e:
        first_error = e.errors()[0] if e.errors() else {}
        loc = " → ".join(str(p) for p in first_error.get("loc", ["root"]))
        msg = first_error.get("msg", str(e))
        logger.error(
            "❌ Validación fallida para tool '%s' en [%s]: %s\nOutput: %s",
            tool_name,
            loc,
            msg,
            output,
        )
        raise ToolOutputValidationError(
            f"Output de '{tool_name}' no pasa validación en [{loc}]: {msg}"
        ) from e

    return output


# ═══════════════════════════════════════════════════════════════════════
# Validación de sugerencias (datos de entrada al grafo)
# ═══════════════════════════════════════════════════════════════════════


class _SuggestionData(BaseModel):
    """Modelo Pydantic para validar datos de sugerencia.

    Complementa la validación de tool suggest_update asegurando que
    los campos requeridos existen antes de persistir en Postgres.
    """

    model_config = ConfigDict(extra="forbid")

    source_doc_id: str = Field(min_length=1)
    confidence_score: float = Field(ge=0.0, le=1.0)
    source_chunk_ids: List[str] = Field(min_length=1)


def validate_suggestion_data(suggestion: dict) -> dict:
    """Valida que un diccionario de sugerencia tenga los campos requeridos.

    Esta validación se ejecuta en generate_suggestions_node ANTES de persistir
    una sugerencia en Postgres, complementando la validación Pydantic
    que ya ocurre dentro de la tool suggest_update.

    Args:
        suggestion: Diccionario con datos de la sugerencia.

    Returns:
        El mismo diccionario si pasa la validación.

    Raises:
        SuggestionDataValidationError: Si falta algún campo requerido o es inválido.
    """
    try:
        _SuggestionData.model_validate(suggestion)
    except PydanticValidationError as e:
        missing = []
        for error in e.errors():
            field = " → ".join(str(p) for p in error.get("loc", []))
            missing.append(field)
        raise SuggestionDataValidationError(
            f"Sugerencia rechazada: campos requeridos faltantes o inválidos: "
            f"{', '.join(missing)}"
        ) from e

    return suggestion


# ═══════════════════════════════════════════════════════════════════════
# Validación de hallazgos de redundancia
# ═══════════════════════════════════════════════════════════════════════


class _RedundancyFinding(BaseModel):
    """Modelo Pydantic para validar hallazgos de redundancia."""

    model_config = ConfigDict(extra="forbid")

    chunk_id_a: str
    chunk_id_b: str
    similarity: float
    confidence_score: float
    doc_id_a: str
    doc_id_b: str
    content_a_preview: str
    content_b_preview: str
    token_count_a: Optional[int] = None
    token_count_b: Optional[int] = None


def validate_redundancy_finding(finding: dict) -> dict:
    """Valida que un hallazgo de redundancia tenga la estructura correcta.

    Args:
        finding: Diccionario con datos del par redundante.

    Returns:
        El mismo diccionario si pasa la validación.

    Raises:
        SuggestionDataValidationError: Si falta algún campo requerido.
    """
    try:
        _RedundancyFinding.model_validate(finding)
    except PydanticValidationError as e:
        missing = []
        for error in e.errors():
            field = " → ".join(str(p) for p in error.get("loc", []))
            missing.append(f"{field}: {error.get('msg', '')}")
        raise SuggestionDataValidationError(
            f"Hallazgo de redundancia rechazado: campos faltantes o inválidos: "
            f"{'; '.join(missing)}"
        ) from e

    return finding


# ═══════════════════════════════════════════════════════════════════════
# Validación de hallazgos de inconsistencia
# ═══════════════════════════════════════════════════════════════════════


# Re-exportamos alias público del modelo interno para uso externo
InconsistencyFinding = _InconsistencyFinding


def validate_inconsistency_finding(finding: dict) -> dict:
    """Valida que un hallazgo de inconsistencia tenga la estructura correcta.

    Args:
        finding: Diccionario con datos del hallazgo de inconsistencia.

    Returns:
        El mismo diccionario si pasa la validación.

    Raises:
        SuggestionDataValidationError: Si falta algún campo requerido.
    """
    try:
        _InconsistencyFinding.model_validate(finding)
    except PydanticValidationError as e:
        missing = []
        for error in e.errors():
            field = " → ".join(str(p) for p in error.get("loc", []))
            missing.append(f"{field}: {error.get('msg', '')}")
        raise SuggestionDataValidationError(
            f"Hallazgo de inconsistencia rechazado: campos faltantes o inválidos: "
            f"{'; '.join(missing)}"
        ) from e

    return finding
