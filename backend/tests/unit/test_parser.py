"""
#26 — Unit tests for parse_document().

Covers:
  - TXT parsing with UTF-8, latin-1, and chardet detection
  - DOCX parsing with mocked python-docx
  - PDF parsing with pdfplumber (success, empty, OCR fallback)
  - OCR fallback with pdf2image + pytesseract
  - Unsupported file type raises ValueError
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from app.utils.parser import parse_document

# ═════════════════════════════════════════════════════════════════════════════
# TXT
# ═════════════════════════════════════════════════════════════════════════════


class TestParseTxt:
    """parse_document() with .txt files."""

    @patch("chardet.detect")
    def test_utf8(self, mock_detect, tmp_data_dir: Path):
        """Parses a UTF-8 encoded text file."""
        content = "Contenido educativo en español: álgebra, geometría."
        filepath = tmp_data_dir / "test_utf8.txt"
        filepath.write_bytes(content.encode("utf-8"))

        mock_detect.return_value = {"encoding": "utf-8", "confidence": 0.99}

        result = parse_document(filepath)
        assert result == content
        mock_detect.assert_called_once()

    @patch("chardet.detect")
    def test_latin1(self, mock_detect, tmp_data_dir: Path):
        """Parses a latin-1 encoded text file."""
        content = "Contenido con acentos: álgebra, geometría, cálculo."
        filepath = tmp_data_dir / "test_latin1.txt"
        filepath.write_bytes(content.encode("latin-1"))

        mock_detect.return_value = {"encoding": "latin-1", "confidence": 0.95}

        result = parse_document(filepath)
        assert result == content
        mock_detect.assert_called_once()

    @patch("chardet.detect")
    def test_empty_file(self, mock_detect, tmp_data_dir: Path):
        """Empty text file returns empty string."""
        filepath = tmp_data_dir / "empty.txt"
        filepath.write_bytes(b"")

        mock_detect.return_value = {"encoding": "utf-8", "confidence": 0.99}

        result = parse_document(filepath)
        assert result == ""

    @patch("chardet.detect")
    def test_fallback_encoding(self, mock_detect, tmp_data_dir: Path):
        """Falls back to utf-8 when encoding detection returns None."""
        content = "Simple text without special chars."
        filepath = tmp_data_dir / "fallback.txt"
        filepath.write_bytes(content.encode("utf-8"))

        mock_detect.return_value = {"encoding": None, "confidence": 0.0}

        result = parse_document(filepath)
        assert result == content

    def test_txt_multiline(self, tmp_data_dir: Path):
        """Multiline text is preserved."""
        content = "Línea 1\nLínea 2\nLínea 3"
        filepath = tmp_data_dir / "multiline.txt"
        filepath.write_bytes(content.encode("utf-8"))

        result = parse_document(filepath)
        assert result == content
        assert "\n" in result


# ═════════════════════════════════════════════════════════════════════════════
# DOCX
# ═════════════════════════════════════════════════════════════════════════════


class TestParseDocx:
    """parse_document() with .docx files."""

    @patch("docx.Document")
    def test_basic(self, mock_document_class, tmp_data_dir: Path):
        """Parses a .docx file extracting paragraph text."""
        filepath = tmp_data_dir / "test.docx"
        filepath.touch()

        mock_doc = MagicMock()
        mock_doc.paragraphs = [
            MagicMock(text="Título del documento"),
            MagicMock(text=""),
            MagicMock(text="Párrafo con contenido educativo."),
            MagicMock(text="Otro párrafo relevante."),
        ]
        mock_document_class.return_value = mock_doc

        result = parse_document(filepath)

        assert "Título del documento" in result
        assert "Párrafo con contenido educativo." in result
        assert "Otro párrafo relevante." in result
        # Empty paragraphs should be excluded
        assert result.count("\n") == 2

    @patch("docx.Document")
    def test_empty_document(self, mock_document_class, tmp_data_dir: Path):
        """Handles document with no text."""
        filepath = tmp_data_dir / "empty.docx"
        filepath.touch()

        mock_doc = MagicMock()
        mock_doc.paragraphs = []
        mock_document_class.return_value = mock_doc

        result = parse_document(filepath)
        assert result == ""

    @patch("docx.Document")
    def test_only_blank_paragraphs(self, mock_document_class, tmp_data_dir: Path):
        """Handles document with only blank paragraphs."""
        filepath = tmp_data_dir / "blank.docx"
        filepath.touch()

        mock_doc = MagicMock()
        mock_doc.paragraphs = [
            MagicMock(text=""),
            MagicMock(text="   "),
            MagicMock(text=""),
        ]
        mock_document_class.return_value = mock_doc

        result = parse_document(filepath)
        assert result == ""


# ═════════════════════════════════════════════════════════════════════════════
# PDF — pdfplumber success
# ═════════════════════════════════════════════════════════════════════════════


class TestParsePdf:
    """parse_document() with .pdf files — pdfplumber path."""

    @patch("pdfplumber.open")
    def test_success(self, mock_pdf_open, tmp_data_dir: Path):
        """Successfully extracts text from PDF via pdfplumber."""
        filepath = tmp_data_dir / "test.pdf"
        filepath.touch()

        mock_page_1 = MagicMock()
        mock_page_1.extract_text.return_value = "Página 1: Introducción al álgebra."
        mock_page_2 = MagicMock()
        mock_page_2.extract_text.return_value = "Página 2: Ecuaciones lineales."

        mock_pdf = MagicMock()
        mock_pdf.__enter__.return_value.pages = [mock_page_1, mock_page_2]
        mock_pdf_open.return_value = mock_pdf

        result = parse_document(filepath)

        assert "Introducción al álgebra" in result
        assert "Ecuaciones lineales" in result
        assert result.startswith("Página 1")

    @patch("pdfplumber.open")
    def test_page_with_no_text(self, mock_pdf_open, tmp_data_dir: Path):
        """Page with no extracted text is skipped."""
        filepath = tmp_data_dir / "test_no_text.pdf"
        filepath.touch()

        mock_page_1 = MagicMock()
        mock_page_1.extract_text.return_value = "Texto visible."
        mock_page_2 = MagicMock()
        mock_page_2.extract_text.return_value = None  # No text on this page
        mock_page_3 = MagicMock()
        mock_page_3.extract_text.return_value = "Más contenido."

        mock_pdf = MagicMock()
        mock_pdf.__enter__.return_value.pages = [mock_page_1, mock_page_2, mock_page_3]
        mock_pdf_open.return_value = mock_pdf

        result = parse_document(filepath)

        assert "Texto visible." in result
        assert "Más contenido." in result
        # Only 2 pages contributed text
        assert result.count("\n") == 1

    @patch("app.utils.parser.logger")
    @patch("pdfplumber.open")
    def test_logging(self, mock_pdf_open, mock_logger, tmp_data_dir: Path):
        """Logs extracted character count."""
        filepath = tmp_data_dir / "test_log.pdf"
        filepath.touch()

        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Hello World"

        mock_pdf = MagicMock()
        mock_pdf.__enter__.return_value.pages = [mock_page]
        mock_pdf_open.return_value = mock_pdf

        parse_document(filepath)

        mock_logger.info.assert_any_call(
            "Extracted PDF text via pdfplumber (%d chars)", 11
        )


# ═════════════════════════════════════════════════════════════════════════════
# PDF — OCR fallback
# ═════════════════════════════════════════════════════════════════════════════


class TestParsePdfOcrFallback:
    """parse_document() OCR fallback when pdfplumber fails."""

    @patch("pytesseract.image_to_string")
    @patch("pdf2image.convert_from_path")
    @patch("pdfplumber.open")
    def test_pdfplumber_exception_triggers_ocr(
        self, mock_pdf_open, mock_convert, mock_tesseract, tmp_data_dir: Path
    ):
        """OCR fallback when pdfplumber raises an exception."""
        filepath = tmp_data_dir / "test_ocr.pdf"
        filepath.touch()

        mock_pdf_open.side_effect = Exception("pdfplumber error")

        mock_img_1 = MagicMock()
        mock_img_2 = MagicMock()
        mock_convert.return_value = [mock_img_1, mock_img_2]

        mock_tesseract.side_effect = [
            "Texto reconocido página 1",
            "Texto reconocido página 2",
        ]

        result = parse_document(filepath)

        assert "Texto reconocido página 1" in result
        assert "Texto reconocido página 2" in result
        assert mock_convert.call_count == 1
        assert mock_tesseract.call_count == 2

    @patch("pytesseract.image_to_string")
    @patch("pdf2image.convert_from_path")
    @patch("pdfplumber.open")
    def test_empty_text_from_pdfplumber_triggers_ocr(
        self, mock_pdf_open, mock_convert, mock_tesseract, tmp_data_dir: Path
    ):
        """OCR fallback when pdfplumber returns empty text."""
        filepath = tmp_data_dir / "test_ocr_empty.pdf"
        filepath.touch()

        mock_page = MagicMock()
        mock_page.extract_text.return_value = ""  # Empty extracted text

        mock_pdf = MagicMock()
        mock_pdf.__enter__.return_value.pages = [mock_page]
        mock_pdf_open.return_value = mock_pdf

        mock_img = MagicMock()
        mock_convert.return_value = [mock_img]
        mock_tesseract.return_value = "Texto extraído por OCR"

        result = parse_document(filepath)

        assert "Texto extraído por OCR" in result
        mock_convert.assert_called_once()

    @patch("pytesseract.image_to_string")
    @patch("pdf2image.convert_from_path")
    @patch("pdfplumber.open")
    def test_ocr_language_params(
        self, mock_pdf_open, mock_convert, mock_tesseract, tmp_data_dir: Path
    ):
        """OCR uses spa+eng language parameters."""
        filepath = tmp_data_dir / "test_ocr_lang.pdf"
        filepath.touch()

        mock_pdf_open.side_effect = Exception("fallback")

        mock_img = MagicMock()
        mock_convert.return_value = [mock_img]
        mock_tesseract.return_value = "Text"

        parse_document(filepath)

        mock_tesseract.assert_called_once_with(mock_img, lang="spa+eng")


# ═════════════════════════════════════════════════════════════════════════════
# Unsupported file type
# ═════════════════════════════════════════════════════════════════════════════


class TestParseUnsupported:
    """parse_document() with unsupported file types."""

    def test_unsupported_extension(self, tmp_data_dir: Path):
        """Raises ValueError for unsupported extensions."""
        filepath = tmp_data_dir / "test.csv"
        filepath.touch()

        with pytest.raises(ValueError, match="Unsupported file type"):
            parse_document(filepath)

    def test_no_extension(self, tmp_data_dir: Path):
        """Raises ValueError for files with no extension."""
        filepath = tmp_data_dir / "README"
        filepath.touch()

        with pytest.raises(ValueError, match="Unsupported file type"):
            parse_document(filepath)

    def test_case_insensitive_extension(self, tmp_data_dir: Path):
        """Handles uppercase .TXT extension correctly."""
        filepath = tmp_data_dir / "README.TXT"
        filepath.write_bytes(b"Hello, World!")

        result = parse_document(filepath)
        assert result == "Hello, World!"
