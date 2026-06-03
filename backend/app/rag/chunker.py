"""
#11 — Chunking 512 tokens + overlap 50
"""
import logging
import hashlib
from typing import Any

import tiktoken

logger = logging.getLogger(__name__)

CHUNK_SIZE = 512
CHUNK_OVERLAP = 50
ENCODING_MODEL = "cl100k_base"


def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[dict[str, Any]]:
    enc = tiktoken.get_encoding(ENCODING_MODEL)
    tokens = enc.encode(text)
    chunks: list[dict[str, Any]] = []

    start = 0
    while start < len(tokens):
        end = start + chunk_size
        chunk_tokens = tokens[start:end]
        chunk_text = enc.decode(chunk_tokens)
        chunk_hash = hashlib.sha256(chunk_text.encode()).hexdigest()

        chunks.append({
            "text": chunk_text,
            "token_count": len(chunk_tokens),
            "hash": chunk_hash,
            "start_token": start,
            "end_token": end,
        })

        step = chunk_size - overlap
        if step <= 0:
            step = chunk_size
        start += step

    logger.info("Chunked %d tokens into %d chunks", len(tokens), len(chunks))
    return chunks
