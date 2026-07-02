"""
#26 — Unit tests for chunk_text().

Covers:
  - Default chunk_size (512) and overlap (50)
  - Empty text returns empty list
  - Short text produces single chunk
  - Exact chunk_size produces one chunk
  - Two chunks with overlap tokens
  - Custom chunk_size and overlap via arguments
  - Hash field is deterministic
  - Token count correctness
"""

from app.rag.chunker import CHUNK_OVERLAP, CHUNK_SIZE, ENCODING_MODEL, chunk_text


class TestChunkerConstants:
    """Chunker default configuration."""

    def test_chunk_size_default(self):
        assert CHUNK_SIZE == 512

    def test_chunk_overlap_default(self):
        assert CHUNK_OVERLAP == 50

    def test_encoding_model(self):
        assert ENCODING_MODEL == "cl100k_base"


class TestChunkTextEdgeCases:
    """Edge case inputs."""

    def test_empty_text(self):
        """Empty text returns empty list."""
        chunks = chunk_text("")
        assert chunks == []

    def test_whitespace_only(self):
        """Whitespace-only text may produce zero or one chunk."""
        chunks = chunk_text("   \n\n   ")
        # Tokenization of whitespace may yield tokens; just verify structure
        assert isinstance(chunks, list)

    def test_single_character(self):
        """Single character produces one chunk."""
        chunks = chunk_text("A")
        assert len(chunks) == 1
        assert chunks[0]["text"] == "A"
        assert chunks[0]["token_count"] == 1
        assert chunks[0]["start_token"] == 0


class TestChunkTextSingleChunk:
    """Text that fits in a single chunk."""

    def test_short_text_produces_one_chunk(self):
        """Short text under chunk_size returns a single chunk."""
        text = "Hello world."
        chunks = chunk_text(text)
        assert len(chunks) == 1
        assert chunks[0]["text"] == text
        assert "token_count" in chunks[0]
        assert "hash" in chunks[0]
        assert "start_token" in chunks[0]
        assert "end_token" in chunks[0]

    def test_chunk_has_expected_fields(self):
        """Each chunk dict contains all required fields."""
        chunks = chunk_text("Test content.")
        chunk = chunks[0]
        assert "text" in chunk
        assert "token_count" in chunk
        assert "hash" in chunk
        assert "start_token" in chunk
        assert "end_token" in chunk


class TestChunkTextMultipleChunks:
    """Text that spans multiple chunks."""

    def test_two_chunks_with_overlap(self):
        """Long text produces multiple chunks with overlapping tokens."""
        # Generate text long enough to require at least 2 chunks of 512 tokens
        words = ["word"] * 600
        text = " ".join(words)

        chunks = chunk_text(text, chunk_size=512, overlap=50)

        assert len(chunks) >= 2

        # Verify overlap: chunk2 starts before chunk1 ends
        assert chunks[1]["start_token"] < chunks[0]["end_token"]
        expected_start = 512 - 50  # step = chunk_size - overlap
        assert chunks[1]["start_token"] == expected_start

    def test_step_at_least_chunk_size_when_overlap_too_large(self):
        """When overlap >= chunk_size, step defaults to chunk_size."""
        text = "word " * 600
        chunks = chunk_text(text, chunk_size=100, overlap=200)

        assert len(chunks) >= 2
        # step should be chunk_size (100), not negative
        assert chunks[1]["start_token"] == 100


class TestChunkTextCustomParams:
    """Custom chunk_size and overlap parameters."""

    def test_custom_chunk_size(self):
        """Custom chunk_size produces chunks of that size."""
        text = "word " * 50
        chunks = chunk_text(text, chunk_size=10, overlap=2)
        # Each chunk should have at most 10 tokens
        for chunk in chunks:
            assert chunk["token_count"] <= 10

    def test_zero_overlap(self):
        """Zero overlap produces contiguous non-overlapping chunks."""
        text = "word " * 600
        chunks = chunk_text(text, chunk_size=100, overlap=0)

        assert len(chunks) >= 2
        assert chunks[1]["start_token"] == 100


class TestChunkHash:
    """Hash field correctness."""

    def test_hash_is_deterministic(self):
        """Same text produces same hash."""
        text = "El álgebra es una rama de las matemáticas."
        chunks_a = chunk_text(text)
        chunks_b = chunk_text(text)

        assert chunks_a[0]["hash"] == chunks_b[0]["hash"]

    def test_different_text_different_hash(self):
        """Different text produces different hash."""
        chunks_a = chunk_text("Contenido A.")
        chunks_b = chunk_text("Contenido B.")

        assert chunks_a[0]["hash"] != chunks_b[0]["hash"]

    def test_hash_is_sha256_hex(self):
        """Hash is a 64-character hex string (SHA-256)."""
        chunks = chunk_text("Some content")
        h = chunks[0]["hash"]
        assert len(h) == 64
        int(h, 16)  # Will raise if not valid hex


class TestChunkTextTokenCount:
    """Token count correctness."""

    def test_token_count_matches_actual_tokens(self):
        """token_count equals the number of encoded tokens."""
        text = "Hello world, this is a test."
        chunks = chunk_text(text)
        assert chunks[0]["token_count"] > 0
        # end_token represents the token position boundary, not the count
        assert chunks[0]["end_token"] >= chunks[0]["token_count"]

    def test_token_count_equals_number_of_encoded_tokens(self):
        """For single chunk, token_count is accurate."""
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        text = "Test token count calculation."
        tokens = enc.encode(text)

        chunks = chunk_text(text)
        assert chunks[0]["token_count"] == len(tokens)
