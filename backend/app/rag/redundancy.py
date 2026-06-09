"""
#14 — Algoritmo redundancia (coseno > 0.90) + confidence score

Detecta información redundante entre chunks comparando sus embeddings
con similitud coseno. El threshold es configurable vía REDUNDANCY_THRESHOLD.

confidence_score es un valor compuesto (0.0–1.0) que refleja:
  - Similitud coseno entre los chunks
  - Longitud del contexto (chunks más largos = más evidencia)
  - Consistencia del chunk (proporción de tokens informativos)
"""

import json
import logging
import math
from typing import List, Optional

from pydantic import BaseModel, Field

from app.config import settings

logger = logging.getLogger(__name__)

# ── Schemas ───────────────────────────────────────────────────────────────────


class RedundancyResult(BaseModel):
    """Par de chunks redundantes con metadatos de la detección."""

    chunk_id_a: str = Field(description="ID del primer chunk en ChromaDB")
    chunk_id_b: str = Field(description="ID del segundo chunk en ChromaDB")
    similarity: float = Field(
        ge=0.0,
        le=1.0,
        description="Similitud coseno entre los embeddings de ambos chunks",
    )
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Confianza compuesta (similitud + contexto + consistencia)",
    )
    doc_id_a: str = Field(description="ID del documento del primer chunk")
    doc_id_b: str = Field(description="ID del documento del segundo chunk")
    chunk_index_a: int = Field(description="Índice del primer chunk")
    chunk_index_b: int = Field(description="Índice del segundo chunk")
    content_a_preview: str = Field(
        description="Preview del contenido del primer chunk (200 chars)"
    )
    content_b_preview: str = Field(
        description="Preview del contenido del segundo chunk (200 chars)"
    )
    token_count_a: int = Field(description="Cantidad de tokens del primer chunk")
    token_count_b: int = Field(description="Cantidad de tokens del segundo chunk")

    model_config = {"frozen": True}


class RedundancyReport(BaseModel):
    """Reporte completo de detección de redundancia."""

    query_chunk_id: str = Field(description="ID del chunk consultado")
    threshold: float = Field(description="Threshold de similitud usado")
    total_comparisons: int = Field(description="Total de comparaciones realizadas")
    redundant_pairs: List[RedundancyResult] = Field(
        description="Pares redundantes encontrados (ordenados por similitud descendente)"
    )
    pair_count: int = Field(description="Cantidad de pares redundantes encontrados")


# ── Funciones auxiliares ──────────────────────────────────────────────────────


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Computa similitud coseno entre dos vectores."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return round(dot / (norm_a * norm_b), 4)


def _compute_confidence_score(
    similarity: float,
    token_count_a: int,
    token_count_b: int,
    content_a: str,
    content_b: str,
) -> float:
    """Calcula un confidence_score compuesto para un par redundante.

    Factores considerados (cada uno 0.0–1.0):
      1. sim_factor:     similitud coseno directa (peso 0.60)
      2. length_factor:  qué tan sustanciosos son ambos chunks (peso 0.25)
      3. consistency:    proporción de contenido informativo (peso 0.15)
    """
    # 1. Similitud coseno (lineal: a mayor similitud, mayor confianza)
    sim_factor = similarity

    # 2. Factor de longitud: prefiero chunks con al menos 50 tokens
    #    Penaliza si algun chunk es muy corto (< 20 tokens)
    avg_tokens = (token_count_a + token_count_b) / 2.0
    if avg_tokens >= 50:
        length_factor = 1.0
    elif avg_tokens <= 20:
        length_factor = 0.3
    else:
        length_factor = 0.3 + 0.7 * (avg_tokens - 20) / 30.0

    # 3. Consistencia: proporción de palabras con longitud > 2 caracteres
    #    (filtra chunks con mucho relleno o caracteres sueltos)
    def _content_consistency(text: str) -> float:
        words = text.split()
        if not words:
            return 0.0
        meaningful = sum(1 for w in words if len(w) > 2)
        return meaningful / len(words)

    consistency_a = _content_consistency(content_a)
    consistency_b = _content_consistency(content_b)
    consistency = (consistency_a + consistency_b) / 2.0

    # Ponderación
    score = 0.60 * sim_factor + 0.25 * length_factor + 0.15 * consistency
    return round(min(max(score, 0.0), 1.0), 4)


# ── Función principal ─────────────────────────────────────────────────────────


async def detect_redundancy(
    chunk_id: str,
    threshold: Optional[float] = None,
    max_pairs: int = 20,
    include_same_doc: bool = True,
) -> RedundancyReport:
    """Detecta chunks redundantes con respecto a un chunk dado.

    Compara el embedding del chunk consultado contra todos los demás
    chunks en ChromaDB y retorna aquellos pares cuya similitud coseno
    supere el threshold configurado.

    Args:
        chunk_id: ID del chunk a evaluar en ChromaDB.
        threshold: Umbral de similitud (0.0–1.0).
                   Por defecto usa REDUNDANCY_THRESHOLD de la configuración.
        max_pairs: Máximo número de pares redundantes a retornar.
        include_same_doc: Si incluir chunks del mismo documento.

    Returns:
        RedundancyReport con los pares redundantes encontrados.
    """
    from app.rag.embeddings import get_chroma_collection

    effective_threshold = (
        threshold if threshold is not None else settings.REDUNDANCY_THRESHOLD
    )
    logger.info(
        "🔍 detect_redundancy(chunk=%s, threshold=%.2f, max_pairs=%d, same_doc=%s)",
        chunk_id,
        effective_threshold,
        max_pairs,
        include_same_doc,
    )

    collection = get_chroma_collection()

    # Obtener el chunk consultado
    query_result = collection.get(
        ids=[chunk_id],
        include=["documents", "metadatas", "embeddings"],
    )

    if not query_result["ids"]:
        logger.warning("  ⚠️  Chunk %s no encontrado en ChromaDB", chunk_id)
        return RedundancyReport(
            query_chunk_id=chunk_id,
            threshold=effective_threshold,
            total_comparisons=0,
            redundant_pairs=[],
            pair_count=0,
        )

    query_embedding = (
        query_result["embeddings"][0] if query_result.get("embeddings") else None
    )
    query_metadata = query_result["metadatas"][0] if query_result["metadatas"] else {}
    query_doc_id = query_metadata.get("doc_id", "")
    query_content = query_result["documents"][0] if query_result["documents"] else ""
    query_token_count = query_metadata.get("token_count", 0)

    if query_embedding is None:
        logger.warning("  ⚠️  Chunk %s no tiene embedding asociado", chunk_id)
        return RedundancyReport(
            query_chunk_id=chunk_id,
            threshold=effective_threshold,
            total_comparisons=0,
            redundant_pairs=[],
            pair_count=0,
        )

    # Obtener todos los chunks para comparar
    all_chunks = collection.get(
        include=["documents", "metadatas", "embeddings"],
    )

    if not all_chunks["ids"]:
        logger.info("  ℹ️  No hay otros chunks en la colección")
        return RedundancyReport(
            query_chunk_id=chunk_id,
            threshold=effective_threshold,
            total_comparisons=0,
            redundant_pairs=[],
            pair_count=0,
        )

    # Comparar contra todos los chunks (excluyéndose a sí mismo)
    redundant_pairs: list[RedundancyResult] = []
    comparisons = 0

    for i in range(len(all_chunks["ids"])):
        other_id = all_chunks["ids"][i]

        # Saltarse a sí mismo
        if other_id == chunk_id:
            continue

        # Saltarse chunks del mismo documento si no se permite
        other_meta = all_chunks["metadatas"][i] if all_chunks["metadatas"] else {}
        if not include_same_doc and other_meta.get("doc_id", "") == query_doc_id:
            continue

        other_embedding = (
            all_chunks["embeddings"][i] if all_chunks.get("embeddings") else None
        )
        if other_embedding is None:
            continue

        similarity = _cosine_similarity(query_embedding, other_embedding)
        comparisons += 1

        if similarity > effective_threshold:
            other_content = (
                all_chunks["documents"][i] if all_chunks["documents"] else ""
            )
            other_token_count = other_meta.get("token_count", 0)

            confidence = _compute_confidence_score(
                similarity=similarity,
                token_count_a=query_token_count,
                token_count_b=other_token_count,
                content_a=query_content,
                content_b=other_content,
            )

            redundant_pairs.append(
                RedundancyResult(
                    chunk_id_a=chunk_id,
                    chunk_id_b=other_id,
                    similarity=similarity,
                    confidence_score=confidence,
                    doc_id_a=query_doc_id,
                    doc_id_b=other_meta.get("doc_id", ""),
                    chunk_index_a=query_metadata.get("chunk_index", 0),
                    chunk_index_b=other_meta.get("chunk_index", 0),
                    content_a_preview=query_content[:200],
                    content_b_preview=other_content[:200],
                    token_count_a=query_token_count,
                    token_count_b=other_token_count,
                )
            )

    # Ordenar por similitud descendente y limitar
    redundant_pairs.sort(key=lambda p: p.similarity, reverse=True)
    redundant_pairs = redundant_pairs[:max_pairs]

    logger.info(
        "  ✅ Redundancia: %d pares encontrados en %d comparaciones (threshold=%.2f)",
        len(redundant_pairs),
        comparisons,
        effective_threshold,
    )

    return RedundancyReport(
        query_chunk_id=chunk_id,
        threshold=effective_threshold,
        total_comparisons=comparisons,
        redundant_pairs=redundant_pairs,
        pair_count=len(redundant_pairs),
    )


async def detect_redundancy_bulk(
    chunk_ids: list[str],
    threshold: Optional[float] = None,
    max_pairs_per_chunk: int = 10,
    include_same_doc: bool = True,
) -> list[RedundancyReport]:
    """Ejecuta detect_redundancy sobre múltiples chunks.

    Útil para procesar todos los chunks de un documento recién insertado.

    Args:
        chunk_ids: Lista de IDs de chunks a evaluar.
        threshold: Umbral de similitud (por defecto REDUNDANCY_THRESHOLD).
        max_pairs_per_chunk: Máximo de pares por chunk.
        include_same_doc: Si incluir redundancia intra-documento.

    Returns:
        Lista de RedundancyReport, uno por cada chunk consultado.
    """
    logger.info(
        "🔍 detect_redundancy_bulk: %d chunks, threshold=%.2f",
        len(chunk_ids),
        threshold or settings.REDUNDANCY_THRESHOLD,
    )

    results: list[RedundancyReport] = []
    for chunk_id in chunk_ids:
        report = await detect_redundancy(
            chunk_id=chunk_id,
            threshold=threshold,
            max_pairs=max_pairs_per_chunk,
            include_same_doc=include_same_doc,
        )
        if report.pair_count > 0:
            results.append(report)

    # Consolidar: eliminar pares duplicados (A-B y B-A)
    seen_pairs: set[frozenset[str]] = set()
    consolidated: list[RedundancyReport] = []
    for report in results:
        unique_pairs: list[RedundancyResult] = []
        for pair in report.redundant_pairs:
            pair_key = frozenset([pair.chunk_id_a, pair.chunk_id_b])
            if pair_key not in seen_pairs:
                seen_pairs.add(pair_key)
                unique_pairs.append(pair)
        if unique_pairs:
            consolidated.append(
                RedundancyReport(
                    query_chunk_id=report.query_chunk_id,
                    threshold=report.threshold,
                    total_comparisons=report.total_comparisons,
                    redundant_pairs=unique_pairs,
                    pair_count=len(unique_pairs),
                )
            )

    total_pairs = sum(r.pair_count for r in consolidated)
    logger.info("  ✅ Bulk completo: %d pares únicos encontrados", total_pairs)
    return consolidated


def redundancy_report_to_json(report: RedundancyReport) -> str:
    """Convierte un RedundancyReport a JSON para consumo del agente."""
    return json.dumps(
        {
            "status": "success",
            "query_chunk_id": report.query_chunk_id,
            "threshold": report.threshold,
            "total_comparisons": report.total_comparisons,
            "redundant_pairs": [
                {
                    "chunk_id_a": p.chunk_id_a,
                    "chunk_id_b": p.chunk_id_b,
                    "similarity": p.similarity,
                    "confidence_score": p.confidence_score,
                    "doc_id_a": p.doc_id_a,
                    "doc_id_b": p.doc_id_b,
                    "content_a_preview": p.content_a_preview,
                    "content_b_preview": p.content_b_preview,
                }
                for p in report.redundant_pairs
            ],
            "pair_count": report.pair_count,
        },
        ensure_ascii=False,
    )
