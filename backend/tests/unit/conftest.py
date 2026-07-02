"""
Shared fixtures for unit tests.

Provides:
  - Sample text constants
  - Temporary file paths (PDF, DOCX, TXT)
  - Mock ChromaDB collection
  - Mock embedding model
"""

import uuid
from pathlib import Path
from tempfile import mkdtemp
from typing import Generator
from unittest.mock import MagicMock

import pytest

# ── Sample text ────────────────────────────────────────────────────────────────

SAMPLE_TEXT_SHORT = "El álgebra es una rama de las matemáticas."

SAMPLE_TEXT_MEDIUM = (
    "El teorema de Pitágoras establece que en un triángulo rectángulo, "
    "el cuadrado de la hipotenusa es igual a la suma de los cuadrados "
    "de los catetos. Esta relación matemática es fundamental en geometría "
    "y tiene numerosas aplicaciones en arquitectura, navegación y topografía."
)

SAMPLE_TEXT_LONG = (
    "El álgebra es una rama de las matemáticas que estudia las estructuras, "
    "las relaciones y las cantidades. Utiliza símbolos y letras para representar "
    "números y cantidades en fórmulas y ecuaciones. Es una herramienta "
    "fundamental para resolver problemas complejos en diversas áreas del "
    "conocimiento. Los conceptos básicos incluyen variables, constantes, "
    "expresiones algebraicas y operaciones fundamentales. Una variable es un "
    "símbolo que representa un valor desconocido o que puede cambiar."
    "\n\n"
    "Una ecuación lineal es una igualdad matemática entre dos expresiones "
    "algebraicas. Se denomina lineal porque las variables involucradas tienen "
    "exponente igual a 1. La forma general es ax + b = 0, donde a y b son "
    "constantes y a es diferente de cero. La solución es x = -b/a."
)

SAMPLE_DOC_ID = str(uuid.uuid4())
SAMPLE_CHUNK_HASH = "abc123def456"


# ── Temporary directories ─────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def tmp_data_dir() -> Generator[Path, None, None]:
    """Temporary directory for test files (once per session)."""
    tmp_dir = Path(mkdtemp(prefix="educurator_unit_"))
    yield tmp_dir
    import shutil

    shutil.rmtree(tmp_dir, ignore_errors=True)


# ── Mock ChromaDB collection ──────────────────────────────────────────────────


@pytest.fixture
def mock_chroma_collection() -> MagicMock:
    """Creates a mock ChromaDB collection with common defaults."""
    collection = MagicMock()
    collection.get.return_value = {
        "ids": [],
        "documents": [],
        "metadatas": [],
        "embeddings": [],
    }
    collection.query.return_value = {
        "ids": [[]],
        "distances": [[]],
        "metadatas": [[]],
        "documents": [[]],
    }
    collection.add = MagicMock()
    return collection


@pytest.fixture
def mock_embedding_model() -> MagicMock:
    """Creates a mock sentence-transformers model."""
    model = MagicMock()
    model.encode.return_value = [0.1] * 384
    return model


@pytest.fixture
def mock_chroma_client(mock_chroma_collection: MagicMock) -> MagicMock:
    """Creates a mock ChromaDB HTTP client."""
    client = MagicMock()
    client.get_or_create_collection.return_value = mock_chroma_collection
    return client
