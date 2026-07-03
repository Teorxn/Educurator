"""
#26 — Unit tests for chunk_and_embed() and embedding model.

Covers:
  - chunk_and_embed with mocked ChromaDB and sentence-transformers
  - Cache hit (hash already exists in ChromaDB)
  - Cache miss (new embedding stored)
  - Metadata correctness (doc_id, category, page_number, chunk_index)
  - chunk_index offset parameter
  - Model singleton pattern
"""

import uuid
from unittest.mock import MagicMock, patch

from app.rag.embeddings import (
    EMBEDDING_MODEL_NAME,
    chunk_and_embed,
)


class TestEmbeddingConstants:
    """Embedding module constants."""

    def test_model_name(self):
        assert EMBEDDING_MODEL_NAME == "paraphrase-multilingual-MiniLM-L12-v2"


class TestGetEmbeddingModel:
    """Singleton model accessor."""

    @patch("sentence_transformers.SentenceTransformer")
    def test_singleton_pattern(self, mock_transformer):
        """_get_embedding_model returns the same instance on second call."""
        # Reset the singleton for test
        import app.rag.embeddings as emb_mod
        from app.rag.embeddings import _get_embedding_model

        emb_mod._embedding_model = None

        model_a = _get_embedding_model()
        model_b = _get_embedding_model()

        assert model_a is model_b
        assert mock_transformer.call_count == 1


class TestChunkAndEmbed:
    """chunk_and_embed() with mocked dependencies."""

    @patch("app.rag.embeddings._get_embedding_model")
    @patch("app.rag.embeddings._get_collection")
    @patch("app.rag.embeddings._get_client")
    @patch("app.rag.chunker.chunk_text")
    def test_success(
        self,
        mock_chunk_text,
        mock_get_client,
        mock_get_collection,
        mock_get_model,
    ):
        """Successfully chunks text, generates embeddings, and stores in ChromaDB."""
        mock_model = MagicMock()
        mock_model.encode.return_value.tolist.return_value = [0.1, 0.2, 0.3]
        mock_get_model.return_value = mock_model

        mock_collection = MagicMock()
        mock_collection.get.return_value = {"ids": [], "metadatas": []}  # Cache miss
        mock_get_collection.return_value = mock_collection

        mock_chunk_text.return_value = [
            {
                "text": "Contenido educativo chunk 1",
                "token_count": 10,
                "hash": "hash_chunk_1",
                "start_token": 0,
                "end_token": 10,
            }
        ]

        doc_id = str(uuid.uuid4())
        results = chunk_and_embed(
            text="Contenido educativo",
            doc_id=doc_id,
            chunk_index=0,
            page_number=5,
            category="curated",
        )

        assert len(results) == 1
        assert results[0]["text"] == "Contenido educativo chunk 1"
        assert results[0]["token_count"] == 10
        assert results[0]["hash"] == "hash_chunk_1"
        assert results[0]["page_number"] == 5
        assert results[0]["category"] == "curated"
        assert results[0]["chunk_index"] == 0

        # Verify embedding was generated (batch API: una llamada con la lista)
        mock_model.encode.assert_called_once_with(
            ["Contenido educativo chunk 1"], batch_size=32, show_progress_bar=False
        )

        # Verify ChromaDB add was called
        mock_collection.add.assert_called_once()
        call_kwargs = mock_collection.add.call_args[1]
        assert doc_id in call_kwargs["ids"][0]
        assert call_kwargs["metadatas"][0]["doc_id"] == doc_id

    @patch("app.rag.embeddings._get_embedding_model")
    @patch("app.rag.embeddings._get_collection")
    @patch("app.rag.embeddings._get_client")
    @patch("app.rag.chunker.chunk_text")
    def test_cache_hit(
        self,
        mock_chunk_text,
        mock_get_client,
        mock_get_collection,
        mock_get_model,
    ):
        """When a chunk hash already exists, reuses existing chroma_id."""
        mock_model = MagicMock()
        mock_get_model.return_value = mock_model

        mock_collection = MagicMock()
        # Simulate cache hit: hash already exists (la consulta en lote
        # retorna el id existente con su hash en metadata)
        mock_collection.get.return_value = {
            "ids": ["existing_chunk_0"],
            "metadatas": [{"hash": "hash_existing"}],
        }
        mock_get_collection.return_value = mock_collection

        mock_chunk_text.return_value = [
            {
                "text": "Contenido repetido",
                "token_count": 5,
                "hash": "hash_existing",
                "start_token": 0,
                "end_token": 5,
            }
        ]

        results = chunk_and_embed(
            text="Contenido repetido",
            doc_id=str(uuid.uuid4()),
        )

        assert len(results) == 1
        assert results[0]["chroma_id"] == "existing_chunk_0"

        # Should NOT generate embedding or add to collection
        mock_model.encode.assert_not_called()
        mock_collection.add.assert_not_called()

    @patch("app.rag.embeddings._get_embedding_model")
    @patch("app.rag.embeddings._get_collection")
    @patch("app.rag.embeddings._get_client")
    @patch("app.rag.chunker.chunk_text")
    def test_cache_miss(
        self,
        mock_chunk_text,
        mock_get_client,
        mock_get_collection,
        mock_get_model,
    ):
        """When chunk hash is new, generates embedding and adds to ChromaDB."""
        mock_model = MagicMock()
        mock_model.encode.return_value.tolist.return_value = [0.5] * 384
        mock_get_model.return_value = mock_model

        mock_collection = MagicMock()
        mock_collection.get.return_value = {"ids": [], "metadatas": []}  # No existing
        mock_get_collection.return_value = mock_collection

        mock_chunk_text.return_value = [
            {
                "text": "Nuevo contenido único",
                "token_count": 8,
                "hash": "hash_new",
                "start_token": 0,
                "end_token": 8,
            }
        ]

        doc_id = str(uuid.uuid4())
        results = chunk_and_embed(
            text="Nuevo contenido único",
            doc_id=doc_id,
        )

        assert len(results) == 1
        # chroma_id should be generated from doc_id
        assert doc_id in results[0]["chroma_id"]

        # Should generate embedding and add to collection
        mock_model.encode.assert_called_once()
        mock_collection.add.assert_called_once()

    @patch("app.rag.embeddings._get_embedding_model")
    @patch("app.rag.embeddings._get_collection")
    @patch("app.rag.embeddings._get_client")
    @patch("app.rag.chunker.chunk_text")
    def test_multiple_chunks(
        self,
        mock_chunk_text,
        mock_get_client,
        mock_get_collection,
        mock_get_model,
    ):
        """Multiple chunks are all processed and stored."""
        mock_model = MagicMock()
        mock_model.encode.return_value.tolist.return_value = [0.1] * 384
        mock_get_model.return_value = mock_model

        mock_collection = MagicMock()
        mock_collection.get.return_value = {"ids": [], "metadatas": []}
        mock_get_collection.return_value = mock_collection

        mock_chunk_text.return_value = [
            {
                "text": f"Chunk {i} content",
                "token_count": 5,
                "hash": f"hash_{i}",
                "start_token": i * 5,
                "end_token": (i + 1) * 5,
            }
            for i in range(3)
        ]

        doc_id = str(uuid.uuid4())
        results = chunk_and_embed(
            text="Some text",
            doc_id=doc_id,
            chunk_index=10,  # Start offset
        )

        assert len(results) == 3
        assert results[0]["chunk_index"] == 10
        assert results[1]["chunk_index"] == 11
        assert results[2]["chunk_index"] == 12
        # Batch API: un solo add con los 3 chunks
        mock_collection.add.assert_called_once()
        call_kwargs = mock_collection.add.call_args[1]
        assert len(call_kwargs["ids"]) == 3

    @patch("app.rag.embeddings._get_embedding_model")
    @patch("app.rag.embeddings._get_collection")
    @patch("app.rag.embeddings._get_client")
    @patch("app.rag.chunker.chunk_text")
    def test_reference_category(
        self,
        mock_chunk_text,
        mock_get_client,
        mock_get_collection,
        mock_get_model,
    ):
        """Reference category is stored in metadata."""
        mock_model = MagicMock()
        mock_model.encode.return_value.tolist.return_value = [0.1] * 384
        mock_get_model.return_value = mock_model

        mock_collection = MagicMock()
        mock_collection.get.return_value = {"ids": [], "metadatas": []}
        mock_get_collection.return_value = mock_collection

        mock_chunk_text.return_value = [
            {
                "text": "Reference content",
                "token_count": 3,
                "hash": "hash_ref",
                "start_token": 0,
                "end_token": 3,
            }
        ]

        results = chunk_and_embed(
            text="Reference content",
            doc_id=str(uuid.uuid4()),
            category="reference",
        )

        assert results[0]["category"] == "reference"

        # Verify metadata passed to ChromaDB
        call_kwargs = mock_collection.add.call_args[1]
        assert call_kwargs["metadatas"][0]["category"] == "reference"
