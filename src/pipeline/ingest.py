"""Stage 0 — create immutable PNG evidence artifacts from a scanned source.

PDFs are rasterized with PDFium and image sources are decoded with Pillow.  The
supported pipeline immediately freezes each prepared page as :class:`PageArtifact`;
the reader and the cockpit can therefore consume the exact same bytes without a
second rasterization or a base64 round trip.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
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

# The supported Tesseract path reads an image whose longest side is capped at this
# size.  Applying the transform while the page artifact is created guarantees that
# its geometry, hash, persisted evidence and OCR input all describe identical bytes.
MAX_READER_LONG_SIDE = 1800

# Raster image extensions we accept directly (a phone photo of the form, a scan).
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}

# PDFium is explicitly not thread-safe. The supported local workflow serializes
# the complete document lifecycle, while direct image ingestion remains concurrent.
_PDFIUM_LOCK = threading.Lock()


class IngestLimitError(RuntimeError):
    """The source exceeds a documented local processing resource budget."""


class IngestDocumentError(RuntimeError):
    """A PDF cannot be parsed or rendered without exposing native error details."""


class ProcessingDeadlineExceeded(RuntimeError):
    """The configured per-sheet processing budget has been exhausted."""


@dataclass(frozen=True, slots=True)
class Deadline:
    """Monotonic, process-local deadline shared by all stages of one intake.

    Wall-clock changes cannot extend the budget.  The clock is injectable solely
    for deterministic tests and is deliberately excluded from equality/repr.
    """

    expires_at: float
    _clock: Callable[[], float] = field(default=time.monotonic, repr=False, compare=False)

    @classmethod
    def after(
        cls,
        seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> Deadline:
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("Processing deadline must be a positive finite number.")
        return cls(expires_at=clock() + seconds, _clock=clock)

    def remaining_seconds(self, *, stage: str = "processing") -> float:
        """Return remaining budget or raise a sanitized fail-closed error."""
        remaining = self.expires_at - self._clock()
        if remaining <= 0:
            raise ProcessingDeadlineExceeded(
                f"Processing deadline exceeded during {stage}; manual review is required."
            )
        return remaining

    def bounded_timeout(self, maximum: float, *, stage: str) -> float:
        """Clamp an adapter timeout to the remaining global budget."""
        if not math.isfinite(maximum) or maximum <= 0:
            raise ValueError("Adapter timeout must be a positive finite number.")
        return min(maximum, self.remaining_seconds(stage=stage))


@dataclass(frozen=True, slots=True)
class PageArtifact:
    """Canonical immutable evidence page consumed by readers and persistence."""

    png_bytes: bytes
    width: int
    height: int
    sha256: str
    page_index: int

    def __post_init__(self) -> None:
        if self.page_index < 0:
            raise ValueError("Page index must be non-negative.")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Page dimensions must be positive.")
        if not self.png_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Page artifact must contain PNG bytes.")
        digest = hashlib.sha256(self.png_bytes).hexdigest()
        if self.sha256 != digest:
            raise ValueError("Page artifact hash does not match its PNG bytes.")

    @classmethod
    def from_image(cls, image: Image.Image, *, page_index: int) -> PageArtifact:
        """Encode one prepared image exactly once as a canonical RGB PNG."""
        converted: Image.Image | None = None
        try:
            prepared = image
            if image.mode != "RGB":
                converted = image.convert("RGB")
                prepared = converted
            buffer = io.BytesIO()
            prepared.save(buffer, format="PNG")
            png_bytes = buffer.getvalue()
            return cls(
                png_bytes=png_bytes,
                width=prepared.width,
                height=prepared.height,
                sha256=hashlib.sha256(png_bytes).hexdigest(),
                page_index=page_index,
            )
        finally:
            if converted is not None:
                converted.close()


def _validate_dpi(dpi: int) -> None:
    if not MIN_DPI <= dpi <= MAX_DPI:
        raise IngestLimitError(f"DPI must be between {MIN_DPI} and {MAX_DPI}.")


def _validate_source_bytes(path: Path) -> None:
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise IngestLimitError("Source exceeds the local byte budget.")


@contextlib.contextmanager
def _pdfium_guard(deadline: Deadline | None):
    """Serialize PDFium access without allowing lock contention to bypass the SLO."""
    if deadline is None:
        acquired = _PDFIUM_LOCK.acquire()
    else:
        acquired = _PDFIUM_LOCK.acquire(
            timeout=deadline.remaining_seconds(stage="PDF renderer queue")
        )
    if not acquired:
        raise ProcessingDeadlineExceeded(
            "Processing deadline exceeded during PDF renderer queue; manual review is required."
        )
    try:
        yield
    finally:
        _PDFIUM_LOCK.release()


def rasterize_pdf(
    path: Path,
    dpi: int = DEFAULT_DPI,
    *,
    deadline: Deadline | None = None,
) -> list[Image.Image]:
    """Rasterize every page of *path* to an RGB PIL image at *dpi*."""
    _validate_dpi(dpi)
    if not path.exists():
        raise FileNotFoundError("PDF source not found.")
    _validate_source_bytes(path)
    if deadline is not None:
        deadline.remaining_seconds(stage="PDF ingestion")

    images: list[Image.Image] = []
    with _pdfium_guard(deadline):
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
                if deadline is not None:
                    deadline.remaining_seconds(stage="PDF validation")
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
                if deadline is not None:
                    deadline.remaining_seconds(stage="PDF rasterization")
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
                    if deadline is not None:
                        deadline.remaining_seconds(stage="PDF rasterization")
                finally:
                    if view is not None:
                        view.close()
                    if bitmap is not None:
                        bitmap.close()
                    page.close()
        except (IngestLimitError, ProcessingDeadlineExceeded):
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


def load_source_images(
    path: Path,
    dpi: int = DEFAULT_DPI,
    *,
    deadline: Deadline | None = None,
) -> list[Image.Image]:
    """Load a source file into page images: PDF → rasterized pages; image → one page.

    Lets the same pipeline accept a scanned PDF or a phone photo of the form.
    """
    _validate_dpi(dpi)
    if not path.exists():
        raise FileNotFoundError("Source file not found.")
    _validate_source_bytes(path)
    if deadline is not None:
        deadline.remaining_seconds(stage="source ingestion")
    if path.suffix.lower() == ".pdf":
        return rasterize_pdf(path, dpi=dpi, deadline=deadline)
    if path.suffix.lower() in _IMAGE_SUFFIXES:
        try:
            with Image.open(path) as img:
                if getattr(img, "n_frames", 1) != 1:
                    raise IngestLimitError("Image must be a single-page v1 document.")
                if img.width * img.height > MAX_PIXELS_PER_PAGE:
                    raise IngestLimitError("Image exceeds the local pixel budget.")
                image = img.convert("RGB")
                if deadline is not None:
                    try:
                        deadline.remaining_seconds(stage="image decoding")
                    except ProcessingDeadlineExceeded:
                        image.close()
                        raise
                return [image]
        except Image.DecompressionBombError:
            raise IngestLimitError("Image exceeds the local pixel budget.") from None
    raise ValueError(
        f"Unsupported source type '{path.suffix}'. Use a PDF or an image "
        f"({', '.join(sorted(_IMAGE_SUFFIXES))})."
    )


def image_to_base64_png(image: Image.Image) -> str:
    """Compatibility encoder for legacy evaluation adapters during migration."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.standard_b64encode(buffer.getvalue()).decode("utf-8")


def downscale_page_image(
    image: Image.Image,
    *,
    max_long_side: int = MAX_READER_LONG_SIDE,
) -> Image.Image:
    """Return the reader-sized image, or the original when no resize is needed.

    Callers must only close the returned image when it is not the input object.
    """
    if max_long_side <= 0:
        raise ValueError("Maximum reader image side must be positive.")
    longest = max(image.width, image.height)
    if longest <= max_long_side:
        return image
    scale = max_long_side / longest
    new_size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def load_page_artifacts(
    path: Path,
    dpi: int = DEFAULT_DPI,
    *,
    deadline: Deadline | None = None,
    max_long_side: int = MAX_READER_LONG_SIDE,
) -> tuple[PageArtifact, ...]:
    """Load and freeze all supported pages, deterministically closing PIL handles."""
    images = load_source_images(path, dpi=dpi, deadline=deadline)
    artifacts: list[PageArtifact] = []
    try:
        for page_index, image in enumerate(images):
            if deadline is not None:
                deadline.remaining_seconds(stage="page preparation")
            prepared = downscale_page_image(image, max_long_side=max_long_side)
            try:
                artifacts.append(PageArtifact.from_image(prepared, page_index=page_index))
            finally:
                if prepared is not image:
                    prepared.close()
            if deadline is not None:
                deadline.remaining_seconds(stage="page encoding")
    finally:
        for image in images:
            image.close()
    return tuple(artifacts)
