"""
#11 — Paquete RAG: chunking, embeddings, y detección de redundancia.

Exporta las funciones principales para procesamiento de documentos.
"""

from app.rag.chunker import chunk_text
from app.rag.embeddings import (
    chunk_and_embed,
    get_chroma_collection,
    get_embedding_model,
)
from app.rag.redundancy import (
    RedundancyReport,
    RedundancyResult,
    detect_redundancy,
    detect_redundancy_bulk,
    detect_redundancy_report,
    redundancy_report_to_json,
    scan_all_redundancy,
)

__all__ = [
    "chunk_and_embed",
    "chunk_text",
    "detect_redundancy",
    "detect_redundancy_bulk",
    "detect_redundancy_report",
    "get_chroma_collection",
    "get_embedding_model",
    "redundancy_report_to_json",
    "RedundancyReport",
    "RedundancyResult",
    "scan_all_redundancy",
]
