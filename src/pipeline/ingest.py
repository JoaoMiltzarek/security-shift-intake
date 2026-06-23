"""Stage 0 — Ingest: load a scanned source (PDF or image) into page images.

VLMs/OCR consume images more reliably than raw PDFs and we want explicit control
over DPI/quality, so the pipeline always works on images. PDFs are rasterized with
PyMuPDF; phone photos / scans (JPG/PNG/...) are opened directly. Provider-agnostic.

Also provides `image_to_base64_png`, the encoding the Anthropic vision API expects
for a base64 image source block.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

import pymupdf
from PIL import Image

# ~250 DPI balances legibility of handwriting against image size/cost (spec §2 stage 0).
DEFAULT_DPI = 250

# Raster image extensions we accept directly (a phone photo of the form, a scan).
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


def rasterize_pdf(path: Path, dpi: int = DEFAULT_DPI) -> list[Image.Image]:
    """Rasterize every page of *path* to an RGB PIL image at *dpi*."""
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    images: list[Image.Image] = []
    doc = pymupdf.open(path)
    try:
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            images.append(img)
    finally:
        doc.close()
    return images


def load_source_images(path: Path, dpi: int = DEFAULT_DPI) -> list[Image.Image]:
    """Load a source file into page images: PDF → rasterized pages; image → one page.

    Lets the same pipeline accept a scanned PDF or a phone photo of the form.
    """
    if not path.exists():
        raise FileNotFoundError(f"Source not found: {path}")
    if path.suffix.lower() == ".pdf":
        return rasterize_pdf(path, dpi=dpi)
    if path.suffix.lower() in _IMAGE_SUFFIXES:
        with Image.open(path) as img:
            return [img.convert("RGB")]
    raise ValueError(
        f"Unsupported source type '{path.suffix}'. Use a PDF or an image "
        f"({', '.join(sorted(_IMAGE_SUFFIXES))})."
    )


def image_to_base64_png(image: Image.Image) -> str:
    """Encode a PIL image as a base64 PNG string (Anthropic image-source `data`)."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.standard_b64encode(buffer.getvalue()).decode("utf-8")
