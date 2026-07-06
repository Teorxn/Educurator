"""
#11 — Embeddings con sentence-transformers + ChromaDB + cache por hash

Usa modelos locales de Hugging Face vía sentence-transformers.
No requiere API key de OpenAI.
"""

import logging
from typing import Any, Optional

import chromadb
import chromadb.api
from chromadb.config import Settings as ChromaSettings

from app.config import settings as app_settings

logger = logging.getLogger(__name__)

COLLECTION_NAME = "document_chunks"

# Modelo multilingüe recomendado para contenido en español
EMBEDDING_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

# Cache del modelo (se carga una sola vez)
_embedding_model = None


def _get_embedding_model():
    """Retorna el modelo de embeddings (singleton)."""
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer

        logger.info("Cargando modelo de embeddings: %s", EMBEDDING_MODEL_NAME)
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        logger.info("Modelo de embeddings cargado correctamente")
    return _embedding_model


def get_embedding_model():
    """Wrapper público para obtener el modelo de embeddings (singleton)."""
    return _get_embedding_model()


def _get_client() -> Any:
    return chromadb.HttpClient(
        host=app_settings.CHROMADB_HOST,
        port=app_settings.CHROMADB_PORT,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def _get_collection(client: Optional[Any] = None):
    c = client or _get_client()
    return c.get_or_create_collection(COLLECTION_NAME)


def get_chroma_collection():
    """Obtiene la colección de ChromaDB para consultas de las tools."""
    return _get_collection()


def chunk_and_embed(
    text: str,
    doc_id: str,
    chunk_index: int = 0,
    page_number: Optional[int] = None,
    category: str = "curated",
) -> list[dict[str, Any]]:
    """Chunkea el texto y genera embeddings locales.

    Cada chunk se almacena en ChromaDB con su hash como metadata
    para evitar recalcular embeddings ya existentes.

    Args:
        text: Texto plano a procesar.
        doc_id: ID del documento en Postgres.
        chunk_index: Índice inicial para numerar chunks.
        page_number: Número de página (opcional).
        category: Categoría del documento ('curated' o 'reference').

    Returns:
        Lista de dicts con chroma_id, chunk_index, text, token_count, hash, page_number, category.
    """
    from app.rag.chunker import chunk_text

    chunks = chunk_text(text)
    if not chunks:
        return []

    client = _get_client()
    collection = _get_collection(client)
    model = _get_embedding_model()

    # ── Cache: una sola consulta por lote (antes: 1 roundtrip por chunk) ──
    # IMPORTANTE: el cache se limita a chunks del MISMO documento. Sin ese
    # filtro, contenido idéntico de otro documento (incluso uno ya borrado)
    # devuelve chroma_ids ajenos; los nodos derivan doc_id del chroma_id y
    # terminan creando sugerencias para documentos inexistentes (FK violation).
    existing_by_hash: dict[str, str] = {}
    try:
        hashes = list({c["hash"] for c in chunks})
        existing = collection.get(
            where={"$and": [{"hash": {"$in": hashes}}, {"doc_id": doc_id}]},
            include=["metadatas"],
        )
        for cid, meta in zip(existing["ids"], existing["metadatas"] or []):
            h = (meta or {}).get("hash")
            if h and h not in existing_by_hash:
                existing_by_hash[h] = cid
    except Exception as e:
        logger.warning("Cache de hashes no disponible, se recalcula todo: %s", e)

    results: list[dict[str, Any]] = []
    new_items: list[tuple[int, dict[str, Any], str]] = []
    batch_hash_to_id: dict[str, str] = {}
    cache_hits = 0

    for i, chunk in enumerate(chunks):
        chunk_hash = chunk["hash"]
        cached_id = existing_by_hash.get(chunk_hash) or batch_hash_to_id.get(chunk_hash)

        if cached_id:
            chroma_id = cached_id
            cache_hits += 1
        else:
            chroma_id = f"{doc_id}_chunk_{chunk_index + i}"
            batch_hash_to_id[chunk_hash] = chroma_id
            new_items.append((i, chunk, chroma_id))

        results.append(
            {
                "chroma_id": chroma_id,
                "chunk_index": chunk_index + i,
                "text": chunk["text"],
                "token_count": chunk["token_count"],
                "hash": chunk_hash,
                "page_number": page_number or 0,
                "category": category,
            }
        )

    # ── Embeddings en lote: un solo encode + un solo add ─────────────────
    if new_items:
        texts = [chunk["text"] for _, chunk, _ in new_items]
        embeddings = model.encode(
            texts, batch_size=32, show_progress_bar=False
        ).tolist()

        collection.add(
            ids=[cid for _, _, cid in new_items],
            embeddings=embeddings,
            documents=texts,
            metadatas=[
                {
                    "doc_id": doc_id,
                    "chunk_index": chunk_index + i,
                    "page_number": page_number or 0,
                    "hash": chunk["hash"],
                    "token_count": chunk["token_count"],
                    "category": category,
                }
                for i, chunk, _ in new_items
            ],
        )

    logger.info(
        "Embeddings doc %s: %d chunks (%d nuevos, %d desde cache)",
        doc_id,
        len(chunks),
        len(new_items),
        cache_hits,
    )
    return results
