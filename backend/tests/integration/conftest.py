"""
Fixtures compartidos para los tests de integracion.

Provee:
  - generacion de PDF real de 5 paginas
  - sesion mockeada de base de datos
  - usuario instructor simulado
  - override de dependencias FastAPI
"""

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from tempfile import mkdtemp
from typing import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.dependencies import get_current_user
from app.main import app
from app.models.models import Document, DocumentCategory, DocumentStatus, UserRole
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ── Ayudantes ─────────────────────────────────────────────────────────────────


def _escape_pdf_string(s: str) -> str:
    """Escapa caracteres especiales para strings PDF."""
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _build_content_stream(lines: list[tuple[str, int, int]]) -> bytes:
    """Construye un content stream PDF.

    Cada linea es (texto, tamano_fuente, posicion_y).
    """
    parts = ["BT"]
    for text, font_size, y_pos in lines:
        escaped = _escape_pdf_string(text)
        parts.append(f"/F1 {font_size} Tf")
        parts.append(f"72 {y_pos} Td")
        parts.append(f"({escaped}) Tj")
    parts.append("ET")
    stream_text = "\n".join(parts)
    return stream_text.encode("latin-1", errors="replace")


def _create_pdf_bytes(pages: list[list[tuple[str, int, int]]]) -> bytes:
    """Genera un PDF valido minimalista con el contenido de las paginas indicadas.

    Cada pagina es una lista de tuplas (texto, tamano_fuente, posicion_y).
    Usa la fuente estandar Helvetica (siempre disponible en lectores PDF).

    Construye todos los objetos primero, luego los escribe en orden numerico
    para que la tabla xref sea correcta.
    """
    num_pages = len(pages)
    # Numeros de objeto:
    # 1 = Catalog
    # 2 = Pages
    # 3 = Font
    # 4 .. 3+num_pages = Page objects
    # 4+num_pages .. 3+2*num_pages = Content stream objects
    font_obj_num = 3
    page_obj_nums = list(range(4, 4 + num_pages))
    stream_obj_nums = list(range(4 + num_pages, 4 + 2 * num_pages))

    # --- Construir todos los objetos como bytestrings ---
    obj_data: dict[int, bytes] = {}

    def set_obj(num: int, data: bytes) -> None:
        obj_data[num] = data

    # Object 1: Catalog
    set_obj(1, b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")

    # Object 2: Pages tree
    kids = " ".join(f"{n} 0 R" for n in page_obj_nums)
    set_obj(
        2,
        f"2 0 obj\n<< /Type /Pages /Kids [{kids}] /Count {num_pages} >>\nendobj\n".encode(),
    )

    # Object 3: Font (Helvetica)
    set_obj(
        3,
        b"3 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    )

    # Generar content streams
    for i, page_lines in enumerate(pages):
        stream_data = _build_content_stream(page_lines)
        font_ref = f"{font_obj_num} 0 R"
        stream_ref = f"{stream_obj_nums[i]} 0 R"

        # Content stream object
        stream_obj = (
            f"{stream_obj_nums[i]} 0 obj\n"
            f"<< /Length {len(stream_data)} >>\n"
            "stream\n".encode()
            + stream_data
            + b"\nendstream\nendobj\n"
        )
        set_obj(stream_obj_nums[i], stream_obj)

        # Page object
        page_dict = (
            f"{page_obj_nums[i]} 0 obj\n"
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
            f" /Contents {stream_ref}"
            f" /Resources << /Font << /F1 {font_ref} >> >> >>\n"
            f"endobj\n"
        )
        set_obj(page_obj_nums[i], page_dict.encode())

    # --- Escribir objetos en orden numerico ---
    buf = bytearray()
    buf.extend(b"%PDF-1.4\n%\xff\xff\xff\xff\n")

    max_obj = max(obj_data.keys())
    offsets: dict[int, int] = {}  # obj_num -> offset

    for num in range(1, max_obj + 1):
        data = obj_data.get(num)
        if data is None:
            continue
        offsets[num] = len(buf)
        buf.extend(data)

    # --- Cross-reference table ---
    xref_offset = len(buf)
    buf.extend(b"xref\n")
    buf.extend(f"0 {max_obj + 1}\n".encode())
    buf.extend(b"0000000000 65535 f \n")
    for num in range(1, max_obj + 1):
        off = offsets.get(num, 0)
        buf.extend(f"{off:010d} 00000 n \n".encode())

    # --- Trailer ---
    buf.extend(
        f"trailer\n"
        f"<< /Size {max_obj + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )

    return bytes(buf)


# ── Construir contenido educativo para 5 paginas ──────────────────────────────

PAGE_1_LINES = [
    ("UNIVERSIDAD NACIONAL DE EDUCACION", 14, 760),
    ("Introduccion al Algebra", 16, 730),
    ("", 11, 710),
    ("El algebra es una rama de las matematicas que estudia las", 11, 690),
    ("estructuras, las relaciones y las cantidades. Utiliza simbolos", 11, 674),
    ("y letras para representar numeros y cantidades en formulas y", 11, 658),
    ("ecuaciones. Es una herramienta fundamental para resolver", 11, 642),
    ("problemas complejos en diversas areas del conocimiento.", 11, 626),
    ("", 11, 606),
    ("Los conceptos basicos incluyen variables, constantes,", 11, 590),
    ("expresiones algebraicas y operaciones fundamentales.", 11, 574),
    ("Una variable es un simbolo que representa un valor", 11, 558),
    ("desconocido o que puede cambiar.", 11, 542),
]

PAGE_2_LINES = [
    ("Ecuaciones Lineales", 16, 760),
    ("", 11, 735),
    ("Una ecuacion lineal es una igualdad matematica entre dos", 11, 715),
    ("expresiones algebraicas. Se denomina lineal porque las", 11, 699),
    ("variables involucradas tienen exponente igual a 1.", 11, 683),
    ("", 11, 663),
    ("Forma general: ax + b = 0, donde a y b son constantes", 11, 647),
    ("y a es diferente de cero. La solucion es x = -b/a.", 11, 631),
    ("", 11, 611),
    ("Las ecuaciones lineales se utilizan para modelar", 11, 595),
    ("situaciones del mundo real como calculo de distancias,", 11, 579),
    ("costos, velocidades y muchas otras aplicaciones.", 11, 563),
    ("", 11, 543),
    ("Ejemplo: 2x + 4 = 10 => x = 3", 11, 527),
]

PAGE_3_LINES = [
    ("Teorema de Pitagoras", 16, 760),
    ("", 11, 735),
    ("El Teorema de Pitagoras es uno de los teoremas fundamentales", 11, 715),
    ("de la geometria. Establece una relacion entre los tres lados", 11, 699),
    ("de un triangulo rectangulo.", 11, 683),
    ("", 11, 663),
    ("En todo triangulo rectangulo, el cuadrado de la hipotenusa", 11, 647),
    ("es igual a la suma de los cuadrados de los catetos.", 11, 631),
    ("", 11, 611),
    ("Formula: c^2 = a^2 + b^2", 11, 595),
    ("donde c es la hipotenusa y a, b son los catetos.", 11, 579),
    ("", 11, 559),
    ("Este teorema tiene numerosas aplicaciones en arquitectura,", 11, 543),
    ("navegacion, topografia y muchas otras disciplinas.", 11, 527),
]

PAGE_4_LINES = [
    ("Funciones y Graficas", 16, 760),
    ("", 11, 735),
    ("Una funcion es una regla de correspondencia entre dos", 11, 715),
    ("conjuntos, donde a cada elemento del conjunto de partida", 11, 699),
    ("le corresponde un unico elemento del conjunto de llegada.", 11, 683),
    ("", 11, 663),
    ("La notacion mas comun es f(x) = y, donde x es la variable", 11, 647),
    ("independiente e y es la variable dependiente.", 11, 631),
    ("", 11, 611),
    ("Las funciones pueden representarse graficamente en el plano", 11, 595),
    ("cartesiano, permitiendo visualizar el comportamiento de la", 11, 579),
    ("relacion entre las variables.", 11, 563),
    ("", 11, 543),
    ("Tipos comunes: lineales, cuadraticas, exponenciales,", 11, 527),
    ("logaritmicas y trigonometricas.", 11, 511),
]

PAGE_5_LINES = [
    ("Estadistica Basica", 16, 760),
    ("", 11, 735),
    ("La estadistica es la ciencia que se ocupa de recopilar,", 11, 715),
    ("organizar, analizar e interpretar datos para tomar decisiones", 11, 699),
    ("informadas en presencia de incertidumbre.", 11, 683),
    ("", 11, 663),
    ("Medidas de tendencia central: la media aritmetica, la mediana", 11, 647),
    ("y la moda son valores que resumen un conjunto de datos.", 11, 631),
    ("", 11, 611),
    ("Medidas de dispersion: la varianza y la desviacion estandar", 11, 595),
    ("indican cuan dispersos estan los datos respecto a la media.", 11, 579),
    ("", 11, 559),
    ("La probabilidad estudia la ocurrencia de eventos aleatorios", 11, 543),
    ("y es la base para la inferencia estadistica.", 11, 527),
]

ALL_PAGES = [PAGE_1_LINES, PAGE_2_LINES, PAGE_3_LINES, PAGE_4_LINES, PAGE_5_LINES]


@pytest.fixture(scope="session")
def pdf_bytes() -> bytes:
    """Genera los bytes del PDF de prueba (una sola vez por sesion)."""
    return _create_pdf_bytes(ALL_PAGES)


@pytest.fixture(scope="session")
def pdf_tmp_dir() -> Generator[Path, None, None]:
    """Directorio temporal para el PDF de prueba (una vez por sesion)."""
    tmp_dir = Path(mkdtemp(prefix="educurator_integration_"))
    yield tmp_dir
    # Limpieza
    import shutil

    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def real_pdf_path(pdf_bytes: bytes, pdf_tmp_dir: Path) -> Path:
    """Crea el archivo PDF real en disco y retorna su ruta."""
    filepath = pdf_tmp_dir / "test_curriculum_5pages.pdf"
    filepath.write_bytes(pdf_bytes)
    logger.info("PDF de prueba creado: %s (%d bytes)", filepath, len(pdf_bytes))
    return filepath


@pytest.fixture(scope="session")
def real_pdf_text(real_pdf_path: Path) -> str:
    """Parsea el PDF real usando pdfplumber y retorna el texto extraido."""
    import pdfplumber

    with pdfplumber.open(str(real_pdf_path)) as pdf:
        text_parts = []
        for i, page in enumerate(pdf.pages, 1):
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
                logger.info("Pagina %d extraida: %d caracteres", i, len(page_text))
    full_text = "\n".join(text_parts)
    logger.info("Texto total extraido del PDF: %d caracteres", len(full_text))
    return full_text


# ── Fixtures para mock de DB ─────────────────────────────────────────────────


@pytest.fixture
def mock_db_session() -> AsyncMock:
    """Crea una sesion de base de datos mockeada con AsyncMock."""
    session = AsyncMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.close = AsyncMock()
    return session


@pytest.fixture
def instructor_user() -> MagicMock:
    """Crea un usuario instructor simulado."""
    return MagicMock(
        id=uuid.uuid4(),
        role=UserRole.instructor,
        email="instructor@test.edu",
        is_active=True,
    )


# ── Fixture para crear un documento mockeado con ruta a PDF real ─────────────


@pytest.fixture
def mock_document_with_pdf(real_pdf_path: Path) -> Document:
    """Crea un Document mock con file_path apuntando al PDF real."""
    doc_id = uuid.uuid4()
    return Document(
        id=doc_id,
        filename="test_curriculum_5pages.pdf",
        original_filename="test_curriculum_5pages.pdf",
        file_type="pdf",
        file_path=str(real_pdf_path),
        size_bytes=real_pdf_path.stat().st_size,
        status=DocumentStatus.needs_review,
        category=DocumentCategory.curated,
        uploaded_by=uuid.uuid4(),
        uploaded_at=datetime.now(timezone.utc),
    )


# ── Fixture para override de auth en tests de API ────────────────────────────


@pytest.fixture(autouse=True)
def override_auth(instructor_user: MagicMock) -> Generator:
    """Sobrescribe la dependencia get_current_user para tests de API."""
    app.dependency_overrides[get_current_user] = lambda: instructor_user
    yield
    app.dependency_overrides.clear()
