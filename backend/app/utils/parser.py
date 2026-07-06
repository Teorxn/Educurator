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
    """OCR para PDFs escaneados (sin capa de texto).

    Requiere poppler (pdf2image) y tesseract. En Docker vienen en la imagen;
    en desarrollo local (Windows/Mac) se configuran vía POPPLER_PATH y
    TESSERACT_CMD en .env si no están en el PATH del sistema.
    """
    import time
    from concurrent.futures import ThreadPoolExecutor

    import pytesseract
    from pdf2image import convert_from_path

    from app.config import settings

    poppler_path = (getattr(settings, "POPPLER_PATH", "") or "").strip() or None
    tesseract_cmd = (getattr(settings, "TESSERACT_CMD", "") or "").strip()
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    # DPI 200: suficiente para texto impreso y ~2x más rápido que 300.
    # Los escaneos de muy baja calidad pueden subirlo vía OCR_DPI en .env.
    dpi = max(72, getattr(settings, "OCR_DPI", 200))
    workers = max(1, getattr(settings, "OCR_WORKERS", 4))

    logger.info(
        "OCR: dpi=%d, workers=%d | poppler=%s | tesseract=%s",
        dpi,
        workers,
        poppler_path or "PATH",
        tesseract_cmd or "PATH",
    )
    started = time.monotonic()

    images = convert_from_path(path, dpi=dpi, poppler_path=poppler_path)

    def _ocr_page(img) -> str:
        # tesseract corre como subproceso → los threads escalan casi lineal
        try:
            return pytesseract.image_to_string(img, lang="spa+eng")
        except pytesseract.TesseractError as e:
            # El paquete de idioma 'spa' puede no estar instalado localmente
            logger.warning("OCR con spa+eng falló (%s) — reintentando solo eng", e)
            return pytesseract.image_to_string(img, lang="eng")

    # Páginas en paralelo, preservando el orden (executor.map lo garantiza)
    with ThreadPoolExecutor(max_workers=min(workers, max(1, len(images)))) as pool:
        text_parts = list(pool.map(_ocr_page, images))

    result = "\n".join(text_parts).strip()
    logger.info(
        "OCR fallback completed (%d pages, %d chars, %.1fs)",
        len(images),
        len(result),
        time.monotonic() - started,
    )
    return result
