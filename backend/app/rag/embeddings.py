"""
#11 — Embeddings con OpenAI + ChromaDB + cache por hash
"""
import logging
import hashlib
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

logger = logging.getLogger(__name__)

COLLECTION_NAME = "document_chunks"
EMBEDDING_MODEL = "text-embedding-3-small"


def _get_client() -> chromadb.HttpClient:
    return chromadb.HttpClient(
        host="chromadb",
        port=8000,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def _get_collection(client: chromadb.HttpClient | None = None):
    c = client or _get_client()
    return c.get_or_create_collection(COLLECTION_NAME)


def chunk_and_embed(
    text: str,
    doc_id: str,
    chunk_index: int = 0,
    page_number: int | None = None,
) -> list[dict[str, Any]]:
    from app.rag.chunker import chunk_text

    chunks = chunk_text(text)
    client = _get_client()
    collection = _get_collection(client)
    from openai import OpenAI

    openai_client = OpenAI()
    results: list[dict[str, Any]] = []

    for i, chunk in enumerate(chunks):
        chunk_hash = chunk["hash"]

        existing = collection.get(where={"hash": chunk_hash})
        if existing and len(existing["ids"]) > 0:
            chroma_id = existing["ids"][0]
            logger.info("Cache hit for chunk hash %s (id=%s)", chunk_hash[:8], chroma_id)
        else:
            resp = openai_client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=chunk["text"],
            )
            embedding = resp.data[0].embedding

            chroma_id = f"{doc_id}_chunk_{chunk_index + i}"
            collection.add(
                ids=[chroma_id],
                embeddings=[embedding],
                documents=[chunk["text"]],
                metadatas=[{
                    "doc_id": doc_id,
                    "chunk_index": chunk_index + i,
                    "page_number": page_number or 0,
                    "hash": chunk_hash,
                    "token_count": chunk["token_count"],
                }],
            )
            logger.info("Stored new embedding for chunk %s", chroma_id)

        results.append({
            "chroma_id": chroma_id,
            "chunk_index": chunk_index + i,
            "text": chunk["text"],
            "token_count": chunk["token_count"],
            "hash": chunk_hash,
            "page_number": page_number or 0,
        })

    return results
