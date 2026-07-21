"""Stage 0 — Ingest: load a scanned source (PDF or image) into page images.

VLMs/OCR consume images more reliably than raw PDFs and we want explicit control
over DPI/quality, so the pipeline always works on images. PDFs are rasterized with
PDFium; phone photos / scans (JPG/PNG/...) are opened directly. Provider-agnostic.

Also provides `image_to_base64_png`, the encoding the Anthropic vision API expects
for a base64 image source block.
"""

from __future__ import annotations

import base64
import contextlib
import io
import math
import threading
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

# ~250 DPI balances legibility of handwriting against image size/cost (spec §2 stage 0).
DEFAULT_DPI = 250

# Local OCR path: real office scans are low-resolution, and rasterizing them high
# upscales noise that *hurts* Tesseract. Empirically (real folhas) OCR is best near
# ~150 DPI for A4. Used by the zero-cost local entry points (demo-pipeline, real eval);
# the VLM path keeps DEFAULT_DPI.
OCR_DPI = 150

# Fail-closed resource budget for the supported single-document local workflow.
MIN_DPI = 50
MAX_DPI = 300
MAX_SOURCE_BYTES = 50 * 1024 * 1024
# The v1 cockpit and schema/identity-validated release dataset are single-page. Reject extra pages
# of presenting page-0 evidence for content extracted from a different page.
MAX_PAGES = 1
MAX_PIXELS_PER_PAGE = 25_000_000
MAX_TOTAL_PIXELS = 75_000_000

# Raster image extensions we accept directly (a phone photo of the form, a scan).
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}

# PDFium is explicitly not thread-safe. The supported local workflow serializes
# the complete document lifecycle, while direct image ingestion remains concurrent.
_PDFIUM_LOCK = threading.Lock()


class IngestLimitError(RuntimeError):
    """The source exceeds a documented local processing resource budget."""


class IngestDocumentError(RuntimeError):
    """A PDF cannot be parsed or rendered without exposing native error details."""


def _validate_dpi(dpi: int) -> None:
    if not MIN_DPI <= dpi <= MAX_DPI:
        raise IngestLimitError(f"DPI must be between {MIN_DPI} and {MAX_DPI}.")


def _validate_source_bytes(path: Path) -> None:
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise IngestLimitError("Source exceeds the local byte budget.")


def rasterize_pdf(path: Path, dpi: int = DEFAULT_DPI) -> list[Image.Image]:
    """Rasterize every page of *path* to an RGB PIL image at *dpi*."""
    _validate_dpi(dpi)
    if not path.exists():
        raise FileNotFoundError("PDF source not found.")
    _validate_source_bytes(path)

    images: list[Image.Image] = []
    with _PDFIUM_LOCK:
        try:
            document = pdfium.PdfDocument(path)
        except Exception:
            raise IngestDocumentError("PDF could not be opened safely.") from None

        try:
            page_count = len(document)
            if page_count != MAX_PAGES:
                raise IngestLimitError("PDF page budget is exactly 1 (single-page v1 document).")

            expected_sizes: list[tuple[int, int]] = []
            total_pixels = 0
            for page_index in range(page_count):
                page = document[page_index]
                try:
                    page_width, page_height = page.get_size()
                finally:
                    page.close()
                width = max(1, math.ceil(float(page_width) * dpi / 72.0))
                height = max(1, math.ceil(float(page_height) * dpi / 72.0))
                pixels = width * height
                if pixels > MAX_PIXELS_PER_PAGE:
                    raise IngestLimitError("PDF page exceeds the local pixel budget.")
                total_pixels += pixels
                if total_pixels > MAX_TOTAL_PIXELS:
                    raise IngestLimitError("PDF exceeds the total local pixel budget.")
                expected_sizes.append((width, height))

            rasterized_pixels = 0
            for page_index, _expected in enumerate(expected_sizes):
                page = document[page_index]
                bitmap = None
                view = None
                try:
                    bitmap = page.render(
                        scale=dpi / 72.0,
                        draw_annots=True,
                        fill_color=(255, 255, 255, 255),
                        rev_byteorder=True,
                    )
                    pixels = bitmap.width * bitmap.height
                    rasterized_pixels += pixels
                    if pixels > MAX_PIXELS_PER_PAGE or rasterized_pixels > MAX_TOTAL_PIXELS:
                        raise IngestLimitError(
                            "Rasterized PDF page exceeds its validated pixel budget."
                        )
                    view = bitmap.to_pil()
                    image = view.copy()
                    if image.mode != "RGB":
                        converted = image.convert("RGB")
                        image.close()
                        image = converted
                    images.append(image)
                finally:
                    if view is not None:
                        view.close()
                    if bitmap is not None:
                        bitmap.close()
                    page.close()
        except IngestLimitError:
            for image in images:
                image.close()
            raise
        except Exception:
            for image in images:
                image.close()
            raise IngestDocumentError("PDF could not be rasterized safely.") from None
        finally:
            with contextlib.suppress(Exception):
                document.close()
    return images


def load_source_images(path: Path, dpi: int = DEFAULT_DPI) -> list[Image.Image]:
    """Load a source file into page images: PDF → rasterized pages; image → one page.

    Lets the same pipeline accept a scanned PDF or a phone photo of the form.
    """
    _validate_dpi(dpi)
    if not path.exists():
        raise FileNotFoundError("Source file not found.")
    _validate_source_bytes(path)
    if path.suffix.lower() == ".pdf":
        return rasterize_pdf(path, dpi=dpi)
    if path.suffix.lower() in _IMAGE_SUFFIXES:
        try:
            with Image.open(path) as img:
                if getattr(img, "n_frames", 1) != 1:
                    raise IngestLimitError("Image must be a single-page v1 document.")
                if img.width * img.height > MAX_PIXELS_PER_PAGE:
                    raise IngestLimitError("Image exceeds the local pixel budget.")
                return [img.convert("RGB")]
        except Image.DecompressionBombError:
            raise IngestLimitError("Image exceeds the local pixel budget.") from None
    raise ValueError(
        f"Unsupported source type '{path.suffix}'. Use a PDF or an image "
        f"({', '.join(sorted(_IMAGE_SUFFIXES))})."
    )


def image_to_base64_png(image: Image.Image) -> str:
    """Encode a PIL image as a base64 PNG string (Anthropic image-source `data`)."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.standard_b64encode(buffer.getvalue()).decode("utf-8")
