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
) -> list[dict[str, Any]]:
    """Chunkea el texto y genera embeddings locales.

    Cada chunk se almacena en ChromaDB con su hash como metadata
    para evitar recalcular embeddings ya existentes.

    Args:
        text: Texto plano a procesar.
        doc_id: ID del documento en Postgres.
        chunk_index: Índice inicial para numerar chunks.
        page_number: Número de página (opcional).

    Returns:
        Lista de dicts con chroma_id, chunk_index, text, token_count, hash, page_number.
    """
    from app.rag.chunker import chunk_text

    chunks = chunk_text(text)
    client = _get_client()
    collection = _get_collection(client)

    model = _get_embedding_model()
    results: list[dict[str, Any]] = []

    for i, chunk in enumerate(chunks):
        chunk_hash = chunk["hash"]

        # Cache: verificar si el hash ya existe en ChromaDB
        existing = collection.get(where={"hash": chunk_hash})
        if existing and len(existing["ids"]) > 0:
            chroma_id = existing["ids"][0]
            logger.info(
                "Cache hit for chunk hash %s (id=%s)", chunk_hash[:8], chroma_id
            )
        else:
            # Generar embedding local con sentence-transformers
            embedding = model.encode(chunk["text"]).tolist()

            chroma_id = f"{doc_id}_chunk_{chunk_index + i}"
            collection.add(
                ids=[chroma_id],
                embeddings=[embedding],
                documents=[chunk["text"]],
                metadatas=[
                    {
                        "doc_id": doc_id,
                        "chunk_index": chunk_index + i,
                        "page_number": page_number or 0,
                        "hash": chunk_hash,
                        "token_count": chunk["token_count"],
                    }
                ],
            )
            logger.info("Stored new embedding for chunk %s", chroma_id)

        results.append(
            {
                "chroma_id": chroma_id,
                "chunk_index": chunk_index + i,
                "text": chunk["text"],
                "token_count": chunk["token_count"],
                "hash": chunk_hash,
                "page_number": page_number or 0,
            }
        )

    return results
