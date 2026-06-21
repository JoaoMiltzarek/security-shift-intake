"""Stage 0 — Ingest: rasterize a scanned PDF into page images.

VLMs consume images more reliably than raw PDFs and we want explicit control over
DPI/quality, so the pipeline always rasterizes first (provider-agnostic). PyMuPDF
(`pymupdf`/`fitz`) does this with no system dependencies.

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


def image_to_base64_png(image: Image.Image) -> str:
    """Encode a PIL image as a base64 PNG string (Anthropic image-source `data`)."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.standard_b64encode(buffer.getvalue()).decode("utf-8")
