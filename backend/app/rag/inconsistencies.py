"""
#60 — Detección de inconsistencias internas y terminológicas en documentos.

Implementa cuatro subtipos de detección:
  1. self_contradiction  — Auto-contradicción dentro de un mismo documento
  2. terminology         — Terminología inconsistente entre documentos
  3. numerical           — Valores numéricos contradictorios
  4. structural          — Inconsistencias de formato/estructura

Cada subtipo retorna una lista de InconsistencyFinding (dicts) que pueden
ser validados contra el modelo Pydantic en guardrails.py.
"""

import logging
import re
from typing import List, Optional

logger = logging.getLogger(__name__)

# ── Configuración ─────────────────────────────────────────────────────────────

# Máximo de pares a evaluar con LLM para self_contradiction
MAX_INCONSISTENCY_PAIRS = 50

# Threshold mínimo de similitud para considerar pares en self_contradiction
SELF_CONTRADICTION_SIMILARITY_THRESHOLD = 0.60

# Variación máxima permitida para la misma magnitud numérica (10%)
NUMERICAL_VARIATION_THRESHOLD = 0.10

# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_llm():
    """Retorna el LLM configurado, o None si no hay.

    Intenta obtener el LLM del módulo de graph (ya configurado como singleton).
    """
    try:
        from app.agents.graph import get_llm

        return get_llm()
    except Exception:
        logger.debug("No hay LLM disponible para detección de inconsistencias")
        return None


def _build_chunk_map(chunks: List[dict]) -> dict:
    """Construye un mapa chroma_id → chunk para búsqueda rápida."""
    return {c.get("chroma_id", ""): c for c in chunks if c.get("chroma_id")}


def _chunks_by_doc(chunks: List[dict]) -> dict:
    """Agrupa chunks por doc_id."""
    groups: dict = {}
    for c in chunks:
        doc_id = c.get("doc_id", "")
        if doc_id not in groups:
            groups[doc_id] = []
        groups[doc_id].append(c)
    return groups


# ═══════════════════════════════════════════════════════════════════════════════
# Subtipo 1: Auto-contradicción (self_contradiction)
# ═══════════════════════════════════════════════════════════════════════════════

_SELF_CONTRADICTION_PROMPT = """Eres un revisor académico experto. Analiza si estos dos fragmentos
del mismo documento son CONTRADICTORIOS entre sí.

Fragmento A: "{extract_a}"
Fragmento B: "{extract_b}"

Responde ÚNICAMENTE con un JSON válido en este formato:
{{
  "is_contradictory": true|false,
  "description": "Explicación breve de por qué son o no contradictorios",
  "suggestion": "Acción recomendada para resolver la contradicción"
}}

Si NO hay contradicción, is_contradictory debe ser false.
"""


async def _evaluate_contradiction_llm(
    extract_a: str,
    extract_b: str,
    llm,
) -> Optional[dict]:
    """Usa el LLM para evaluar si dos fragmentos son contradictorios."""
    try:
        prompt = _SELF_CONTRADICTION_PROMPT.format(
            extract_a=extract_a[:500],
            extract_b=extract_b[:500],
        )
        from langchain_core.messages import HumanMessage

        response = await llm.ainvoke([HumanMessage(content=prompt)])
        content = response.content.strip()
        # Extraer JSON de la respuesta
        import json

        # Buscar bloque JSON delimitado por ``` o usarlo directamente
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group(1))
        else:
            # Intentar parse directo
            result = json.loads(content)
        return result
    except Exception as e:
        logger.warning("Error evaluando contradicción con LLM: %s", e)
        return None


async def detect_self_contradictions(
    chunks: List[dict],
    max_pairs: int = MAX_INCONSISTENCY_PAIRS,
) -> List[dict]:
    """Detecta auto-contradicciones dentro de cada documento.

    Compara todos los chunks de un mismo documento entre sí usando el LLM
    para evaluar si hay contradicción. Usa similitud coseno como pre-filtro
    para reducir pares a evaluar (threshold 0.60).
    """
    findings: List[dict] = []
    llm = _get_llm()
    if not llm:
        logger.info("  ℹ️  self_contradiction requiere LLM — saltando")
        return findings

    docs = _chunks_by_doc(chunks)
    pairs_evaluated = 0

    for doc_id, doc_chunks in docs.items():
        if len(doc_chunks) < 2:
            continue

        # Pre-filtrar con similitud coseno si hay embeddings disponibles
        candidates = _prefilter_by_similarity(
            doc_chunks,
            threshold=SELF_CONTRADICTION_SIMILARITY_THRESHOLD,
        )

        for chunk_a, chunk_b in candidates:
            if pairs_evaluated >= max_pairs:
                logger.info("  ℹ️  Alcanzado límite de %d pares a evaluar", max_pairs)
                return findings

            extract_a = chunk_a.get("text", chunk_a.get("content", ""))[:300]
            extract_b = chunk_b.get("text", chunk_b.get("content", ""))[:300]

            result = await _evaluate_contradiction_llm(extract_a, extract_b, llm)
            pairs_evaluated += 1

            if result and result.get("is_contradictory"):
                finding = {
                    "type": "self_contradiction",
                    "severity": "high",
                    "chunk_id_a": chunk_a.get("chroma_id", ""),
                    "chunk_id_b": chunk_b.get("chroma_id", ""),
                    "doc_id_a": doc_id,
                    "doc_id_b": doc_id,
                    "extract_a": extract_a,
                    "extract_b": extract_b,
                    "description": result.get("description", ""),
                    "suggestion": result.get("suggestion", ""),
                }
                findings.append(finding)
                logger.info(
                    "  🔍 Auto-contradicción encontrada en doc %s: %s",
                    doc_id,
                    result.get("description", "")[:100],
                )

    logger.info(
        "  ✅ self_contradiction: %d hallazgos de %d pares evaluados",
        len(findings),
        pairs_evaluated,
    )
    return findings


def _prefilter_by_similarity(
    doc_chunks: List[dict],
    threshold: float = 0.60,
    max_candidates: int = 100,
) -> List[tuple]:
    """Pre-filtra pares de chunks usando similitud coseno.

    Si no hay embeddings disponibles, retorna todos los pares posibles
    (limitado a max_candidates).
    """
    candidates: List[tuple] = []
    try:
        from app.rag.redundancy import _cosine_similarity

        for i in range(len(doc_chunks)):
            for j in range(i + 1, len(doc_chunks)):
                emb_a = doc_chunks[i].get("embedding")
                emb_b = doc_chunks[j].get("embedding")
                if emb_a and emb_b:
                    sim = _cosine_similarity(emb_a, emb_b)
                    if sim >= threshold:
                        candidates.append((doc_chunks[i], doc_chunks[j]))
                else:
                    # Sin embedding, incluir como candidato
                    candidates.append((doc_chunks[i], doc_chunks[j]))

                if len(candidates) >= max_candidates:
                    return candidates
    except Exception as e:
        logger.debug(
            "Error en pre-filtro por similitud: %s — usando todos los pares", e
        )
        # Fallback: todos los pares (limitado)
        for i in range(len(doc_chunks)):
            for j in range(i + 1, len(doc_chunks)):
                candidates.append((doc_chunks[i], doc_chunks[j]))
                if len(candidates) >= max_candidates:
                    return candidates

    return candidates


# ═══════════════════════════════════════════════════════════════════════════════
# Subtipo 2: Terminología (terminology)
# ═══════════════════════════════════════════════════════════════════════════════

_TERMINOLOGY_EXTRACTION_PROMPT = """Eres un analista de contenido educativo. Extrae los términos clave
y sus definiciones del siguiente fragmento de documento académico.

Fragmento:
"{text}"

Responde ÚNICAMENTE con un JSON válido en este formato:
{{
  "terms": [
    {{"term": "nombre del término", "definition": "definición textual", "context": "oración donde aparece"}}
  ]
}}

Si no hay términos relevantes, retorna {{"terms": []}}.
"""


async def _extract_terms_from_text(text: str, llm) -> List[dict]:
    """Extrae términos y definiciones usando el LLM."""
    try:
        prompt = _TERMINOLOGY_EXTRACTION_PROMPT.format(text=text[:1500])
        from langchain_core.messages import HumanMessage

        response = await llm.ainvoke([HumanMessage(content=prompt)])
        content = response.content.strip()
        import json

        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group(1))
        else:
            result = json.loads(content)
        return result.get("terms", [])
    except Exception as e:
        logger.warning("Error extrayendo términos: %s", e)
        return []


async def detect_terminology_issues(
    chunks: List[dict],
    existing_terminology_map: Optional[dict] = None,
) -> tuple[List[dict], dict]:
    """Detecta inconsistencias terminológicas entre documentos.

    Extrae términos clave de cada documento y los compara contra
    otros documentos del mismo grupo. Detecta:
    - Sinónimos conflictivos (mismo concepto, nombre diferente)
    - Homónimos (mismo nombre, definición diferente)

    Retorna (findings, updated_terminology_map).
    """
    findings: List[dict] = []
    llm = _get_llm()
    if not llm:
        logger.info("  ℹ️  terminology requiere LLM — saltando")
        return findings, existing_terminology_map or {}

    terminology_map = dict(existing_terminology_map or {})
    docs = _chunks_by_doc(chunks)

    for doc_id, doc_chunks in docs.items():
        if doc_id in terminology_map:
            continue  # Ya extraído (caché)

        full_text = " ".join(c.get("text", c.get("content", "")) for c in doc_chunks)
        terms = await _extract_terms_from_text(full_text, llm)
        if terms:
            terminology_map[doc_id] = terms

    # Comparar glosarios entre documentos
    doc_ids = list(terminology_map.keys())
    for i in range(len(doc_ids)):
        for j in range(i + 1, len(doc_ids)):
            doc_a = doc_ids[i]
            doc_b = doc_ids[j]
            terms_a = terminology_map[doc_a]
            terms_b = terminology_map[doc_b]

            # Buscar homónimos: mismo término, definición diferente
            terms_a_dict = {t["term"].lower(): t for t in terms_a}
            for tb in terms_b:
                t_name = tb["term"].lower()
                if t_name in terms_a_dict:
                    ta = terms_a_dict[t_name]
                    # Comparar definiciones (si son muy diferentes)
                    if _definitions_differ(ta["definition"], tb["definition"]):
                        finding = {
                            "type": "terminology",
                            "severity": "medium",
                            "chunk_id_a": "",
                            "chunk_id_b": "",
                            "doc_id_a": doc_a,
                            "doc_id_b": doc_b,
                            "extract_a": f"Término '{tb['term']}': {ta['definition']}",
                            "extract_b": f"Término '{tb['term']}': {tb['definition']}",
                            "description": (
                                f"El término '{tb['term']}' tiene definiciones "
                                f"distintas en documentos diferentes"
                            ),
                            "suggestion": (
                                f"Unificar la definición de '{tb['term']}' "
                                f"en ambos documentos"
                            ),
                        }
                        findings.append(finding)

            # Buscar sinónimos conflictivos: términos diferentes, misma definición
            for ta in terms_a:
                for tb in terms_b:
                    if ta["term"].lower() == tb["term"].lower():
                        continue
                    if _definitions_similar(ta["definition"], tb["definition"]):
                        finding = {
                            "type": "terminology",
                            "severity": "low",
                            "chunk_id_a": "",
                            "chunk_id_b": "",
                            "doc_id_a": doc_a,
                            "doc_id_b": doc_b,
                            "extract_a": f"'{ta['term']}': {ta['definition']}",
                            "extract_b": f"'{tb['term']}': {tb['definition']}",
                            "description": (
                                f"Los términos '{ta['term']}' y '{tb['term']}' "
                                f"parecen referirse al mismo concepto"
                            ),
                            "suggestion": (
                                "Considerar usar un único término para ambos documentos"
                            ),
                        }
                        findings.append(finding)

    logger.info(
        "  ✅ terminology: %d hallazgos de %d documentos",
        len(findings),
        len(doc_ids),
    )
    return findings, terminology_map


def _definitions_differ(def_a: str, def_b: str) -> bool:
    """Determina si dos definiciones son significativamente diferentes."""
    # Normalizar
    a = def_a.lower().strip()
    b = def_b.lower().strip()
    if not a or not b:
        return False
    # Si comparten palabras clave, asumir que son iguales
    words_a = set(a.split())
    words_b = set(b.split())
    if len(words_a) < 3 or len(words_b) < 3:
        return a != b
    intersection = words_a & words_b
    # Si menos del 40% de palabras coinciden, son diferentes
    return len(intersection) / max(len(words_a), len(words_b)) < 0.4


def _definitions_similar(def_a: str, def_b: str) -> bool:
    """Determina si dos definiciones se refieren al mismo concepto."""
    a = def_a.lower().strip()
    b = def_b.lower().strip()
    if not a or not b:
        return False
    words_a = set(a.split())
    words_b = set(b.split())
    intersection = words_a & words_b
    return len(intersection) / max(len(words_a), len(words_b)) > 0.6


# ═══════════════════════════════════════════════════════════════════════════════
# Subtipo 3: Numérica (numerical)
# ═══════════════════════════════════════════════════════════════════════════════

_NUMERIC_PATTERN = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(horas?s|h|días?|d|semanas?|meses?|años?|"
    r"créditos?|ECTS|%|euros?|€|dólares?|\$|GB|MB|KB|gigabytes?|megabytes?|"
    r"kilobytes?|minutos?|segundos?|participantes?|alumnos?|estudiantes?|"
    r"plazas?|unidades?|módulos?|temas?|lecciones?|sesiones?|veces?)",
    re.IGNORECASE,
)


def _extract_numeric_entities(text: str, chunk_id: str) -> List[dict]:
    """Extrae entidades numéricas con contexto de un fragmento de texto."""
    entities: List[dict] = []
    for match in _NUMERIC_PATTERN.finditer(text):
        value_str = match.group(1).replace(",", ".")
        try:
            value = float(value_str)
        except ValueError:
            continue
        unit = match.group(2).lower().strip()
        # Obtener contexto (oración alrededor)
        start = max(0, match.start() - 50)
        end = min(len(text), match.end() + 50)
        context = text[start:end].strip()
        entities.append(
            {
                "value": value,
                "unit": unit,
                "context": context,
                "chunk_id": chunk_id,
            }
        )
    return entities


def _normalize_unit(unit: str) -> str:
    """Normaliza unidades a una forma canónica."""
    unit_map = {
        "h": "horas",
        "hora": "horas",
        "horas": "horas",
        "d": "días",
        "día": "días",
        "dias": "días",
        "días": "días",
        "semana": "semanas",
        "semanas": "semanas",
        "mes": "meses",
        "meses": "meses",
        "año": "años",
        "anos": "años",
        "años": "años",
        "%": "porcentaje",
        "€": "euros",
        "euro": "euros",
        "euros": "euros",
        "$": "dolares",
        "dólar": "dolares",
        "dolar": "dolares",
        "dolares": "dolares",
        "crédito": "creditos",
        "creditos": "creditos",
        "créditos": "creditos",
        "ects": "ects",
    }
    return unit_map.get(unit, unit)


def detect_numerical_inconsistencies(chunks: List[dict]) -> List[dict]:
    """Detecta valores numéricos contradictorios entre chunks.

    Compara todas las entidades numéricas con la misma unidad
    y reporta aquellas cuya variación supere el 10%.
    """
    findings: List[dict] = []

    # Extraer todas las entidades numéricas
    all_entities: List[dict] = []
    for c in chunks:
        text = c.get("text", c.get("content", ""))
        chunk_id = c.get("chroma_id", "")
        doc_id = c.get("doc_id", "")
        entities = _extract_numeric_entities(text, chunk_id)
        for e in entities:
            e["doc_id"] = doc_id
        all_entities.extend(entities)

    # Agrupar por unidad normalizada
    by_unit: dict = {}
    for e in all_entities:
        unit = _normalize_unit(e["unit"])
        if unit not in by_unit:
            by_unit[unit] = []
        by_unit[unit].append(e)

    # Buscar contradicciones dentro de cada unidad
    for unit, entities in by_unit.items():
        if len(entities) < 2:
            continue

        # Agrupar por doc_id para detectar también intra-documento
        for i in range(len(entities)):
            for j in range(i + 1, len(entities)):
                ea = entities[i]
                eb = entities[j]
                if ea["doc_id"] == eb["doc_id"]:
                    # Intra-documento: cualquier diferencia significativa es relevante
                    min_val = min(ea["value"], eb["value"])
                    max_val = max(ea["value"], eb["value"])
                    if min_val == 0:
                        continue
                    variation = (max_val - min_val) / min_val
                else:
                    # Inter-documento: solo si describen la misma métrica
                    # (detectado por similitud de contexto)
                    if not _contexts_describe_same_metric(ea["context"], eb["context"]):
                        continue
                    min_val = min(ea["value"], eb["value"])
                    max_val = max(ea["value"], eb["value"])
                    if min_val == 0:
                        continue
                    variation = (max_val - min_val) / min_val

                if variation > NUMERICAL_VARIATION_THRESHOLD:
                    finding = {
                        "type": "numerical",
                        "severity": "high" if variation > 0.50 else "medium",
                        "chunk_id_a": ea["chunk_id"],
                        "chunk_id_b": eb["chunk_id"],
                        "doc_id_a": ea["doc_id"],
                        "doc_id_b": eb["doc_id"],
                        "extract_a": ea["context"],
                        "extract_b": eb["context"],
                        "description": (
                            f"Valores numéricos contradictorios en '{unit}': "
                            f"{ea['value']} vs {eb['value']} "
                            f"(variación: {variation:.1%})"
                        ),
                        "suggestion": (
                            f"Revisar y unificar el valor de '{unit}' "
                            f"en los documentos afectados"
                        ),
                    }
                    findings.append(finding)

    logger.info(
        "  ✅ numerical: %d hallazgos de %d entidades",
        len(findings),
        len(all_entities),
    )
    return findings


def _contexts_describe_same_metric(ctx_a: str, ctx_b: str) -> bool:
    """Determina si dos contextos describen la misma métrica.

    Usa palabras clave compartidas como heurística simple.
    """
    # Palabras clave comunes en descripciones de métricas educativas
    key_phrases = [
        "duració",
        "duración",
        "duracion",
        "crédito",
        "credito",
        "horas",
        "semana",
        "mes",
        "año",
        "total",
        "curso",
        "programa",
        "módulo",
        "modulo",
        "materia",
        "asignatura",
    ]
    a_lower = ctx_a.lower()
    b_lower = ctx_b.lower()
    for phrase in key_phrases:
        if phrase in a_lower and phrase in b_lower:
            return True
    # Si no hay frase clave, usar superposición de palabras
    words_a = set(a_lower.split())
    words_b = set(b_lower.split())
    return len(words_a & words_b) >= 3


# ═══════════════════════════════════════════════════════════════════════════════
# Subtipo 4: Estructural (structural)
# ═══════════════════════════════════════════════════════════════════════════════

# Patrones de encabezados
_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

# Patrones de estilos de cita
_CITATION_APA = re.compile(r"\([^)]*\d{4}[^)]*\)")
_CITATION_VANCOUVER = re.compile(r"\[\d+(?:[-,]\d+)*\]")
_CITATION_FOOTNOTE = re.compile(r"\[\^[^\]]+\]")

# Secciones obligatorias sugeridas para documentos educativos
_REQUIRED_SECTIONS = [
    "objetivo",
    "objetivos",
    "introducción",
    "introduccion",
    "metodología",
    "metodologia",
    "contenido",
    "contenidos",
    "evaluación",
    "evaluacion",
    "bibliografía",
    "bibliografia",
    "referencia",
    "referencias",
]


def _detect_heading_inconsistencies(text: str) -> List[dict]:
    """Detecta patrones inconsistentes de encabezados.

    Busca:
    - Saltos de nivel (ej: h1 → h3 sin h2 intermedio)
    - Títulos huérfanos (h2 sin h1 previo)
    """
    issues: List[dict] = []
    headings = _HEADING_PATTERN.findall(text)

    if not headings:
        return issues

    prev_level = None
    for level_str, title in headings:
        level = len(level_str)
        if prev_level is not None:
            # Salto de nivel > 1
            if level > prev_level + 1:
                issues.append(
                    {
                        "issue": "heading_jump",
                        "description": (
                            f"Salto de nivel de encabezado: "
                            f"de h{prev_level} a h{level} ('{title.strip()}')"
                        ),
                        "suggestion": (
                            f"Usar h{prev_level + 1} en lugar de h{level} "
                            f"para '{title.strip()}'"
                        ),
                    }
                )
        prev_level = level

    # Títulos huérfanos: h2/h3 sin h1 en el documento
    has_h1 = any(len(level_str) == 1 for level_str, _ in headings)
    if not has_h1 and headings:
        issues.append(
            {
                "issue": "orphan_headings",
                "description": "El documento no tiene un encabezado de nivel 1 (h1)",
                "suggestion": "Agregar un título principal con # (h1) al inicio del documento",
            }
        )

    return issues


def _detect_citation_style_mixing(text: str) -> List[dict]:
    """Detecta estilos de cita mixtos dentro de un documento."""
    styles_found = []
    if _CITATION_APA.search(text):
        styles_found.append("APA")
    if _CITATION_VANCOUVER.search(text):
        styles_found.append("Vancouver")
    if _CITATION_FOOTNOTE.search(text):
        styles_found.append("nota al pie")

    if len(styles_found) >= 2:
        return [
            {
                "issue": "mixed_citation_styles",
                "description": (
                    f"Estilos de cita mixtos detectados: {', '.join(styles_found)}"
                ),
                "suggestion": (
                    f"Unificar al estilo {styles_found[0]} en todo el documento"
                ),
            }
        ]
    return []


def _detect_missing_required_sections(text: str) -> List[dict]:
    """Detecta secciones obligatorias faltantes."""
    text_lower = text.lower()
    missing = []
    for section in _REQUIRED_SECTIONS:
        # Buscar como encabezado
        if not re.search(rf"^#+\s*{section}", text_lower, re.MULTILINE):
            missing.append(section)

    if missing:
        return [
            {
                "issue": "missing_sections",
                "description": (
                    f"Secciones obligatorias no encontradas: {', '.join(missing)}"
                ),
                "suggestion": (
                    "Agregar las secciones faltantes siguiendo la plantilla del curso"
                ),
            }
        ]
    return []


def detect_structural_inconsistencies(chunks: List[dict]) -> List[dict]:
    """Detecta inconsistencias estructurales en los documentos.

    Analiza: encabezados, estilos de cita, secciones obligatorias.
    """
    findings: List[dict] = []
    docs = _chunks_by_doc(chunks)

    for doc_id, doc_chunks in docs.items():
        full_text = " ".join(c.get("text", c.get("content", "")) for c in doc_chunks)
        if not full_text.strip():
            continue

        # Encabezados
        heading_issues = _detect_heading_inconsistencies(full_text)
        for issue in heading_issues:
            findings.append(
                {
                    "type": "structural",
                    "severity": "low",
                    "chunk_id_a": "",
                    "chunk_id_b": "",
                    "doc_id_a": doc_id,
                    "doc_id_b": doc_id,
                    "extract_a": issue["description"],
                    "extract_b": "",
                    "description": issue["description"],
                    "suggestion": issue["suggestion"],
                }
            )

        # Estilos de cita
        citation_issues = _detect_citation_style_mixing(full_text)
        for issue in citation_issues:
            findings.append(
                {
                    "type": "structural",
                    "severity": "low",
                    "chunk_id_a": "",
                    "chunk_id_b": "",
                    "doc_id_a": doc_id,
                    "doc_id_b": doc_id,
                    "extract_a": issue["description"],
                    "extract_b": "",
                    "description": issue["description"],
                    "suggestion": issue["suggestion"],
                }
            )

        # Secciones obligatorias
        section_issues = _detect_missing_required_sections(full_text)
        for issue in section_issues:
            findings.append(
                {
                    "type": "structural",
                    "severity": "medium",
                    "chunk_id_a": "",
                    "chunk_id_b": "",
                    "doc_id_a": doc_id,
                    "doc_id_b": doc_id,
                    "extract_a": issue["description"],
                    "extract_b": "",
                    "description": issue["description"],
                    "suggestion": issue["suggestion"],
                }
            )

    logger.info(
        "  ✅ structural: %d hallazgos en %d documentos",
        len(findings),
        len(docs),
    )
    return findings


# ═══════════════════════════════════════════════════════════════════════════════
# API pública
# ═══════════════════════════════════════════════════════════════════════════════


async def detect_all_inconsistencies(
    chunks: List[dict],
    terminology_map: Optional[dict] = None,
    enable_llm: bool = True,
    max_pairs: int = MAX_INCONSISTENCY_PAIRS,
) -> tuple:
    """Ejecuta todos los subtipos de detección de inconsistencias.

    Args:
        chunks: Lista de chunks del estado.
        terminology_map: Mapa de terminología existente (para caché).
        enable_llm: Si False, salta los subtipos que requieren LLM.
        max_pairs: Máximo de pares a evaluar en self_contradiction.

    Returns:
        Tuple de (all_findings, updated_terminology_map).
    """
    all_findings: List[dict] = []

    # Subtipos que NO requieren LLM (siempre se ejecutan)
    logger.info("  🔢 Detectando inconsistencias numéricas...")
    numerical_findings = detect_numerical_inconsistencies(chunks)
    all_findings.extend(numerical_findings)

    logger.info("  🏗️  Detectando inconsistencias estructurales...")
    structural_findings = detect_structural_inconsistencies(chunks)
    all_findings.extend(structural_findings)

    # Subtipos que requieren LLM (solo si enable_llm y hay LLM)
    if enable_llm:
        logger.info("  🔍 Detectando auto-contradicciones...")
        sc_findings = await detect_self_contradictions(chunks, max_pairs)
        all_findings.extend(sc_findings)

        logger.info("  📝 Detectando inconsistencias terminológicas...")
        term_findings, updated_terminology = await detect_terminology_issues(
            chunks,
            terminology_map,
        )
        all_findings.extend(term_findings)
    else:
        updated_terminology = terminology_map or {}

    logger.info(
        "  📊 Total de inconsistencias encontradas: %d",
        len(all_findings),
    )
    return all_findings, updated_terminology
