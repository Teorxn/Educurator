"""
#10 — Parser PDF/DOCX/TXT con OCR fallback (pytesseract)
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def parse_document(file_path: str | Path) -> str:
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext == ".pdf":
        return _parse_pdf(path)
    elif ext == ".docx":
        return _parse_docx(path)
    elif ext == ".txt":
        return _parse_txt(path)
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def _parse_pdf(path: Path) -> str:
    import pdfplumber

    text_parts: list[str] = []
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
    except Exception:
        logger.warning("pdfplumber failed, falling back to OCR: %s", path)
        return _ocr_fallback(path)

    result = "\n".join(text_parts).strip()
    if not result:
        logger.info("No text extracted via pdfplumber, trying OCR: %s", path)
        return _ocr_fallback(path)

    logger.info("Extracted PDF text via pdfplumber (%d chars)", len(result))
    return result


def _parse_docx(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    result = "\n".join(paragraphs).strip()
    logger.info("Extracted DOCX text (%d chars)", len(result))
    return result


def _parse_txt(path: Path) -> str:
    import chardet

    raw = path.read_bytes()
    detected = chardet.detect(raw)
    encoding = detected.get("encoding", "utf-8") or "utf-8"
    text = raw.decode(encoding, errors="replace")
    logger.info("Extracted TXT text (%d chars, encoding=%s)", len(text), encoding)
    return text.strip()


def _ocr_fallback(path: Path) -> str:
    from pdf2image import convert_from_path
    import pytesseract

    images = convert_from_path(path, dpi=300)
    text_parts: list[str] = []
    for i, img in enumerate(images):
        page_text = pytesseract.image_to_string(img, lang="spa+eng")
        text_parts.append(page_text)
        logger.debug("OCR page %d: %d chars", i + 1, len(page_text))

    result = "\n".join(text_parts).strip()
    logger.info("OCR fallback completed (%d pages, %d chars)", len(images), len(result))
    return result
