"""
#14 — Algoritmo redundancia (coseno > 0.90) + confidence score

Detecta información redundante entre chunks comparando sus embeddings
con similitud coseno. El threshold es configurable vía REDUNDANCY_THRESHOLD.

confidence_score es un valor compuesto (0.0–1.0) que refleja:
  - Similitud coseno entre los chunks
  - Longitud del contexto (chunks más largos = más evidencia)
  - Consistencia del chunk (proporción de tokens informativos)
"""

import asyncio
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


# ── Helpers de async ───────────────────────────────────────────────────────────


def _safe_get_embeddings(data, idx: int) -> Optional[list[float]]:
    """Extrae el embedding en `idx` de `data`, retornando None si no existe."""
    try:
        emb = data["embeddings"][idx] if data.get("embeddings") else None
        return emb
    except (IndexError, TypeError):
        return None


def _safe_get_content(data, idx: int) -> str:
    """Extrae el contenido en `idx` de `data`, retornando '' si no existe."""
    try:
        return data["documents"][idx] if data.get("documents") else ""
    except (IndexError, TypeError):
        return ""


def _safe_get_metadata(data, idx: int) -> dict:
    """Extrae metadatos en `idx` de `data`, retornando {} si no existe."""
    try:
        return data["metadatas"][idx] if data.get("metadatas") else {}
    except (IndexError, TypeError):
        return {}


def _index_chunks_by_id(data: dict) -> dict[str, dict]:
    """Indexa chunks de ChromaDB por ID para acceso rápido."""
    by_id: dict[str, dict] = {}
    for i in range(len(data.get("ids", []))):
        cid = data["ids"][i]
        by_id[cid] = {
            "embedding": _safe_get_embeddings(data, i),
            "metadata": _safe_get_metadata(data, i),
            "content": _safe_get_content(data, i),
        }
    return by_id


# ── Función pública (acorde a la especificación de la issue) ───────────────────


async def detect_redundancy(
    chunk_id: str,
    threshold: Optional[float] = None,
    max_pairs: int = 20,
    include_same_doc: bool = True,
) -> list[RedundancyResult]:
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
        Lista de RedundancyResult con los pares redundantes encontrados.
    """
    report = await detect_redundancy_report(
        chunk_id=chunk_id,
        threshold=threshold,
        max_pairs=max_pairs,
        include_same_doc=include_same_doc,
    )
    return report.redundant_pairs


# ── Función con reporte detallado ───────────────────────────────────────────────


async def detect_redundancy_report(
    chunk_id: str,
    threshold: Optional[float] = None,
    max_pairs: int = 20,
    include_same_doc: bool = True,
) -> RedundancyReport:
    """Detecta chunks redundantes y retorna un reporte completo.

    Esta es la implementación interna que genera metadatos adicionales
    (total de comparaciones, umbral usado, etc.).
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

    # ── Obtener el chunk consultado (en thread para no bloquear el event loop) ──
    query_result = await asyncio.to_thread(
        collection.get,
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

    query_embedding = _safe_get_embeddings(query_result, 0)
    query_metadata = _safe_get_metadata(query_result, 0)
    query_doc_id = query_metadata.get("doc_id", "")
    query_content = _safe_get_content(query_result, 0)
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

    # ── Obtener todos los chunks para comparar (en thread) ────────────────────
    all_chunks = await asyncio.to_thread(
        collection.get,
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

    # ── Comparar contra todos los chunks ──────────────────────────────────────
    redundant_pairs: list[RedundancyResult] = []
    comparisons = 0

    for i in range(len(all_chunks["ids"])):
        other_id = all_chunks["ids"][i]

        # Saltarse a sí mismo
        if other_id == chunk_id:
            continue

        # Saltarse chunks del mismo documento si no se permite
        other_meta = _safe_get_metadata(all_chunks, i)
        if not include_same_doc and other_meta.get("doc_id", "") == query_doc_id:
            continue

        other_embedding = _safe_get_embeddings(all_chunks, i)
        if other_embedding is None:
            continue

        similarity = _cosine_similarity(query_embedding, other_embedding)
        comparisons += 1

        if similarity > effective_threshold:
            other_content = _safe_get_content(all_chunks, i)
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
    """Ejecuta detección de redundancia sobre múltiples chunks en una sola pasada.

    A diferencia de llamar detect_redundancy() N veces, esta función obtiene
    todos los chunks de ChromaDB una sola vez y calcula las similitudes en
    memoria, reduciendo drásticamente las llamadas a la base de datos vectorial.

    Args:
        chunk_ids: Lista de IDs de chunks a evaluar.
        threshold: Umbral de similitud (por defecto REDUNDANCY_THRESHOLD).
        max_pairs_per_chunk: Máximo de pares por chunk.
        include_same_doc: Si incluir redundancia intra-documento.

    Returns:
        Lista de RedundancyReport, uno por cada chunk consultado.
    """
    from app.rag.embeddings import get_chroma_collection

    effective_threshold = (
        threshold if threshold is not None else settings.REDUNDANCY_THRESHOLD
    )
    logger.info(
        "🔍 detect_redundancy_bulk: %d chunks, threshold=%.2f",
        len(chunk_ids),
        effective_threshold,
    )

    if not chunk_ids:
        return []

    collection = get_chroma_collection()

    # 1. Obtener SOLO los chunks consultados (en thread para no bloquear)
    query_data = await asyncio.to_thread(
        collection.get,
        ids=chunk_ids,
        include=["documents", "metadatas", "embeddings"],
    )

    if not query_data["ids"]:
        logger.info("  ℹ️  Ningún chunk consultado encontrado en ChromaDB")
        return []

    # 2. Obtener TODOS los otros chunks (una sola llamada, en thread)
    all_data = await asyncio.to_thread(
        collection.get,
        include=["documents", "metadatas", "embeddings"],
    )

    if not all_data["ids"]:
        logger.info("  ℹ️  No hay otros chunks en la colección")
        return []

    # 3. Indexar todos los chunks por ID para acceso rápido
    all_by_id = _index_chunks_by_id(all_data)

    # 4. Para cada chunk consultado, comparar contra todos
    seen_pairs: set[frozenset[str]] = set()
    consolidated: list[RedundancyReport] = []

    for chunk_id in chunk_ids:
        if chunk_id not in all_by_id:
            logger.warning("  ⚠️  Chunk %s no encontrado en ChromaDB", chunk_id)
            continue

        query_info = all_by_id[chunk_id]
        query_embedding = query_info["embedding"]
        query_metadata = query_info["metadata"]
        query_doc_id = query_metadata.get("doc_id", "")
        query_content = query_info["content"]
        query_token_count = query_metadata.get("token_count", 0)

        if query_embedding is None:
            logger.warning("  ⚠️  Chunk %s no tiene embedding", chunk_id)
            continue

        pairs: list[RedundancyResult] = []
        comparisons = 0

        for other_id, other_info in all_by_id.items():
            # Saltarse a sí mismo
            if other_id == chunk_id:
                continue

            other_meta = other_info["metadata"]

            # Saltarse chunks del mismo documento si no se permite
            if not include_same_doc and other_meta.get("doc_id", "") == query_doc_id:
                continue

            other_embedding = other_info["embedding"]
            if other_embedding is None:
                continue

            similarity = _cosine_similarity(query_embedding, other_embedding)
            comparisons += 1

            if similarity > effective_threshold:
                other_content = other_info["content"]
                other_token_count = other_meta.get("token_count", 0)

                # Evitar duplicados (A-B y B-A)
                pair_key = frozenset([chunk_id, other_id])
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                confidence = _compute_confidence_score(
                    similarity=similarity,
                    token_count_a=query_token_count,
                    token_count_b=other_token_count,
                    content_a=query_content,
                    content_b=other_content,
                )

                pairs.append(
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
        pairs.sort(key=lambda p: p.similarity, reverse=True)
        pairs = pairs[:max_pairs_per_chunk]

        if pairs:
            consolidated.append(
                RedundancyReport(
                    query_chunk_id=chunk_id,
                    threshold=effective_threshold,
                    total_comparisons=comparisons,
                    redundant_pairs=pairs,
                    pair_count=len(pairs),
                )
            )

    total_pairs = sum(r.pair_count for r in consolidated)
    logger.info(
        "  ✅ Bulk optimizado: %d pares únicos en %d chunks",
        total_pairs,
        len(chunk_ids),
    )
    return consolidated


async def scan_all_redundancy(
    threshold: Optional[float] = None,
    max_pairs: int = 50,
    include_same_doc: bool = False,
) -> list[RedundancyResult]:
    """Escanea toda la colección ChromaDB buscando pares redundantes.

    A diferencia de detect_redundancy() que busca redundancia contra UN chunk,
    esta función compara todos los chunks contra todos y retorna los pares
    más redundantes de toda la colección.

    Útil para:
      - Ejecutar como mantenimiento periódico
      - Detectar redundancia entre documentos existentes al subir uno nuevo
      - Obtener una vista global del estado de redundancia

    Args:
        threshold: Umbral de similitud (por defecto REDUNDANCY_THRESHOLD).
        max_pairs: Máximo de pares a retornar (ordenados por similitud descendente).
        include_same_doc: Si incluir redundancia intra-documento.

    Returns:
        Lista global de RedundancyResult, ordenados por similitud descendente.
    """
    from app.rag.embeddings import get_chroma_collection

    effective_threshold = (
        threshold if threshold is not None else settings.REDUNDANCY_THRESHOLD
    )
    logger.info(
        "🔍 scan_all_redundancy(threshold=%.2f, max_pairs=%d, same_doc=%s)",
        effective_threshold,
        max_pairs,
        include_same_doc,
    )

    collection = get_chroma_collection()

    # Obtener todos los chunks (en thread para no bloquear)
    all_data = await asyncio.to_thread(
        collection.get,
        include=["documents", "metadatas", "embeddings"],
    )

    if not all_data["ids"] or len(all_data["ids"]) < 2:
        logger.info("  ℹ️  No hay suficientes chunks para comparar")
        return []

    # Indexar por ID para acceso rápido
    all_by_id = _index_chunks_by_id(all_data)
    ids_list = list(all_by_id.keys())
    total_chunks = len(ids_list)
    max_comparisons = settings.MAX_REDUNDANCY_COMPARISONS

    if total_chunks > max_comparisons:
        logger.warning(
            "  ⚠️  Colección grande (%d chunks). Limitando a %d comparaciones. "
            "Ajusta MAX_REDUNDANCY_COMPARISONS si es necesario.",
            total_chunks,
            max_comparisons,
        )

    seen_pairs: set[frozenset[str]] = set()
    all_pairs: list[RedundancyResult] = []
    total_comparisons = 0

    for i in range(total_chunks):
        if total_comparisons >= max_comparisons:
            logger.info(
                "  ⚠️  Límite de %d comparaciones alcanzado. "
                "Procesando resultados parciales.",
                max_comparisons,
            )
            break

        chunk_id_a = ids_list[i]
        info_a = all_by_id[chunk_id_a]
        emb_a = info_a["embedding"]
        meta_a = info_a["metadata"]
        doc_id_a = meta_a.get("doc_id", "")
        content_a = info_a["content"]
        token_a = meta_a.get("token_count", 0)

        if emb_a is None:
            continue

        for j in range(i + 1, total_chunks):
            if total_comparisons >= max_comparisons:
                break

            chunk_id_b = ids_list[j]
            info_b = all_by_id[chunk_id_b]
            emb_b = info_b["embedding"]
            meta_b = info_b["metadata"]

            if emb_b is None:
                continue

            # Excluir mismo documento si no se permite
            if not include_same_doc and meta_b.get("doc_id", "") == doc_id_a:
                continue

            total_comparisons += 1
            similarity = _cosine_similarity(emb_a, emb_b)

            if similarity > effective_threshold:
                pair_key = frozenset([chunk_id_a, chunk_id_b])
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                content_b = info_b["content"]
                token_b = meta_b.get("token_count", 0)

                confidence = _compute_confidence_score(
                    similarity=similarity,
                    token_count_a=token_a,
                    token_count_b=token_b,
                    content_a=content_a,
                    content_b=content_b,
                )

                all_pairs.append(
                    RedundancyResult(
                        chunk_id_a=chunk_id_a,
                        chunk_id_b=chunk_id_b,
                        similarity=similarity,
                        confidence_score=confidence,
                        doc_id_a=doc_id_a,
                        doc_id_b=meta_b.get("doc_id", ""),
                        chunk_index_a=meta_a.get("chunk_index", 0),
                        chunk_index_b=meta_b.get("chunk_index", 0),
                        content_a_preview=content_a[:200],
                        content_b_preview=content_b[:200],
                        token_count_a=token_a,
                        token_count_b=token_b,
                    )
                )

    # Ordenar por similitud descendente y limitar
    all_pairs.sort(key=lambda p: p.similarity, reverse=True)
    all_pairs = all_pairs[:max_pairs]

    logger.info(
        "  ✅ Scan completo: %d pares encontrados en %d comparaciones (threshold=%.2f)",
        len(all_pairs),
        total_comparisons,
        effective_threshold,
    )
    return all_pairs


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
