"""Persist and serve the OCR page image the cockpit overlay draws on.

The overlay boxes are normalized against the *downscaled* image Tesseract read
(`downscale_for_ocr`), so we persist that exact image — not the pretty original —
under a per-document uuid dir inside the gitignored `private/` tree (PII never leaves
`private/`). Serving is index-only and path-safe: a stored path is rejoined to the
configured root and rejected if it resolves outside it, so a tampered `state_json`
can never read an arbitrary file.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import tempfile
import uuid
from collections.abc import Sequence
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from src.paths import PRIVATE_ROOT, resolve_private_path
from src.pipeline.ingest import PageArtifact
from src.schema.evidence import PageArtifactRef

# Default root for persisted page images — inside the gitignored private/ tree.
PAGE_IMAGES_ROOT = PRIVATE_ROOT / "page_images"


def _page_root(root: Path) -> Path:
    """Validate the release default; explicit alternate roots are test injection."""
    if root == PAGE_IMAGES_ROOT:
        resolved = resolve_private_path(root, create_root=True)
        resolved.mkdir(exist_ok=True)
        return resolve_private_path(resolved)
    resolved = root.resolve(strict=False)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def save_page_artifacts(
    pages: Sequence[PageArtifact],
    root: Path = PAGE_IMAGES_ROOT,
) -> list[PageArtifactRef]:
    """Atomically persist the exact PNG bytes read by the document reader.

    Paths are relative to *root* (e.g. ``"<uuid>/page_0.png"``) so the stored state is
    portable and the serving endpoint controls the absolute location.
    """
    root = _page_root(root)
    if not pages:
        raise ValueError("At least one page artifact is required.")
    key = uuid.uuid4().hex
    page_dir = root / key
    staging = Path(tempfile.mkdtemp(prefix=f".{key}-", dir=root))
    try:
        for expected_index, page in enumerate(pages):
            if page.page_index != expected_index:
                raise ValueError("Page artifact indexes must be contiguous and ordered.")
            (staging / f"page_{expected_index}.png").write_bytes(page.png_bytes)
        os.replace(staging, page_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return [
        PageArtifactRef(
            storage_key=(Path(key) / f"page_{page.page_index}.png").as_posix(),
            sha256=page.sha256,
            width=page.width,
            height=page.height,
        )
        for page in pages
    ]


class PageArtifactIntegrityError(RuntimeError):
    """Stored evidence no longer matches the identity captured at ingestion."""


def _resolve_page_path(refs: list[PageArtifactRef], n: int, root: Path) -> Path:
    root = _page_root(root)
    if n < 0 or n >= len(refs):
        raise FileNotFoundError(f"page index {n} out of range")
    candidate = (root / refs[n].storage_key).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise PermissionError(f"page path escapes root: {refs[n].storage_key!r}")
    if not candidate.is_file():
        raise FileNotFoundError(f"page image not found: {candidate}")
    return candidate


def read_page_image(
    refs: list[PageArtifactRef], n: int, root: Path = PAGE_IMAGES_ROOT
) -> bytes:
    """Return bytes only after validating their hash, format, and dimensions."""
    path = _resolve_page_path(refs, n, root)
    payload = path.read_bytes()
    ref = refs[n]
    if hashlib.sha256(payload).hexdigest() != ref.sha256:
        raise PageArtifactIntegrityError("page image hash does not match persisted evidence")
    try:
        with Image.open(io.BytesIO(payload)) as image:
            image.load()
            if image.format != "PNG" or image.size != (ref.width, ref.height):
                raise PageArtifactIntegrityError(
                    "page image format or dimensions do not match persisted evidence"
                )
    except (UnidentifiedImageError, OSError) as exc:
        raise PageArtifactIntegrityError("page image is not a valid PNG") from exc
    return payload


def resolve_page_image(
    refs: list[PageArtifactRef], n: int, root: Path = PAGE_IMAGES_ROOT
) -> Path:
    """Resolve page *n* to an absolute file path, rejecting bad indexes and traversal.

    Raises FileNotFoundError for an out-of-range index or a missing file, and
    PermissionError if the stored path resolves outside *root* (defense in depth
    against a tampered state_json). Both map to a 404 at the endpoint.
    """
    path = _resolve_page_path(refs, n, root)
    read_page_image(refs, n, root)
    return path
