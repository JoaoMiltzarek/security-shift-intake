"""Persist and serve the OCR page image the cockpit overlay draws on.

The overlay boxes are normalized against the *downscaled* image Tesseract read
(`downscale_for_ocr`), so we persist that exact image — not the pretty original —
under a per-document uuid dir inside the gitignored `private/` tree (PII never leaves
`private/`). Serving is index-only and path-safe: a stored path is rejoined to the
configured root and rejected if it resolves outside it, so a tampered `state_json`
can never read an arbitrary file.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from PIL import Image

from src.clients.local_ocr import downscale_for_ocr

# Default root for persisted page images — inside the gitignored private/ tree.
PAGE_IMAGES_ROOT = Path("private/page_images")


def save_page_images(images: list[Image.Image], root: Path = PAGE_IMAGES_ROOT) -> list[str]:
    """Save each page (downscaled like Tesseract saw it) and return POSIX rel paths.

    Paths are relative to *root* (e.g. ``"<uuid>/page_0.png"``) so the stored state is
    portable and the serving endpoint controls the absolute location.
    """
    key = uuid.uuid4().hex
    page_dir = root / key
    page_dir.mkdir(parents=True, exist_ok=True)
    rel_paths: list[str] = []
    for n, image in enumerate(images):
        rel = Path(key) / f"page_{n}.png"
        downscale_for_ocr(image).save(root / rel, format="PNG")
        rel_paths.append(rel.as_posix())
    return rel_paths


def resolve_page_image(
    rel_paths: list[str], n: int, root: Path = PAGE_IMAGES_ROOT
) -> Path:
    """Resolve page *n* to an absolute file path, rejecting bad indexes and traversal.

    Raises FileNotFoundError for an out-of-range index or a missing file, and
    PermissionError if the stored path resolves outside *root* (defense in depth
    against a tampered state_json). Both map to a 404 at the endpoint.
    """
    if n < 0 or n >= len(rel_paths):
        raise FileNotFoundError(f"page index {n} out of range")
    candidate = (root / rel_paths[n]).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise PermissionError(f"page path escapes root: {rel_paths[n]!r}")
    if not candidate.is_file():
        raise FileNotFoundError(f"page image not found: {candidate}")
    return candidate
