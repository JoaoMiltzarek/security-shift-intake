"""TesseractReader — zero-cost, offline document reading.

Consumes the canonical immutable PNG page directly (no base64 encode/decode) and
returns line-preserving text plus Tesseract word geometry.  The subprocess timeout
is bounded by the intake's global monotonic deadline.

HONEST LIMITATION (§4): Tesseract reads printed text well but is weak on cursive
handwriting. Low-confidence/garbled output is expected on handwritten values — the
critic flags those MUST_REVIEW and the human corrects them in the review screen.
This is the OCR + rules + human-in-the-loop design (à la ExpenseIt), not "trust the
OCR".
"""

from __future__ import annotations

import io
import os
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytesseract
from PIL import Image

from src.clients.base import TranscriptionResult, WordBox
from src.paths import PRIVATE_ROOT, resolve_private_path
from src.pipeline.ingest import (
    Deadline,
    PageArtifact,
    ProcessingDeadlineExceeded,
    downscale_page_image,
)

# Real office scans are low-resolution; rasterizing them at high DPI upscales the
# noise and *hurts* Tesseract. Empirically (real folhas) OCR peaks near ~150 DPI for
# A4, so we cap the longest side before OCR — large inputs are downscaled, small
# synthetic renders are left untouched.
_MAX_OCR_LONG_SIDE = 1800

# Boxes must serve the *same* image the cockpit displays, so geometry and pixels
# share one transform. Rounding can push a fraction a hair past [0,1]; clamp that.
# Anything wildly out is a real bug — discard the word, never clamp it silently.
_CLAMP_EPS = 0.01
TESSERACT_TIMEOUT_SECONDS = 120.0
TESSERACT_TEMP_ROOT = PRIVATE_ROOT / "tmp" / "tesseract"
_TESSERACT_TEMP_LOCK = threading.Lock()


def tesseract_available() -> bool:
    """Return whether the local Tesseract executable is callable."""
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:  # noqa: BLE001 - every discovery failure means unavailable
        return False


@contextmanager
def _tesseract_private_temp(root: Path) -> Iterator[None]:
    """Route pytesseract and its subprocess temp files to a private, purgable root."""
    if root == TESSERACT_TEMP_ROOT:
        root = resolve_private_path(root, create_root=True)
        root.mkdir(parents=True, exist_ok=True)
    else:
        root = root.expanduser().resolve(strict=False)
        root.mkdir(parents=True, exist_ok=True)

    with _TESSERACT_TEMP_LOCK:
        previous_tempdir = tempfile.tempdir
        previous_env = {name: os.environ.get(name) for name in ("TMP", "TEMP", "TMPDIR")}
        private_temp = str(root)
        tempfile.tempdir = private_temp
        os.environ.update({name: private_temp for name in previous_env})
        try:
            yield
        finally:
            tempfile.tempdir = previous_tempdir
            for name, value in previous_env.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


def downscale_for_ocr(image: Image.Image) -> Image.Image:
    """Compatibility alias for the canonical artifact preparation transform."""
    return downscale_page_image(image, max_long_side=_MAX_OCR_LONG_SIDE)


def _norm_coord(value: float, *, name: str) -> float | None:
    """Normalize one fraction: clamp tiny rounding overshoot, reject absurd values."""
    if -_CLAMP_EPS <= value < 0.0 or 1.0 < value <= 1.0 + _CLAMP_EPS:
        return min(1.0, max(0.0, value))
    if 0.0 <= value <= 1.0:
        return value
    if os.environ.get("INTAKE_LOCATOR_DEBUG") == "1":
        # Never log the OCR text itself (may be PII) — only the coordinate that failed.
        print(f"[locator] dropped a word box: {name}={value:.4f} out of [0,1]")
    return None


def _collect_words(data: dict[str, Any], width: int, height: int) -> list[WordBox]:
    """Build normalized WordBoxes from image_to_data; drop empty/low-conf/absurd words."""
    words: list[WordBox] = []
    if width <= 0 or height <= 0:
        return words
    for i in range(len(data["text"])):
        text = str(data["text"][i]).strip()
        if not text:
            continue
        conf = float(data["conf"][i])
        if conf < 0:  # Tesseract emits -1 for non-text regions
            continue
        left, top = float(data["left"][i]), float(data["top"][i])
        w, h = float(data["width"][i]), float(data["height"][i])
        if w <= 0 or h <= 0:  # degenerate box → not a real word region
            continue
        x0 = _norm_coord(left / width, name="x0")
        y0 = _norm_coord(top / height, name="y0")
        x1 = _norm_coord((left + w) / width, name="x1")
        y1 = _norm_coord((top + h) / height, name="y1")
        if x0 is None or y0 is None or x1 is None or y1 is None:
            continue
        if x0 >= x1 or y0 >= y1:
            continue
        line_key = (
            f"{int(data['block_num'][i])}:{int(data['par_num'][i])}:{int(data['line_num'][i])}"
        )
        words.append(
            WordBox(
                text=text,
                bbox=(x0, y0, x1, y1),
                conf=min(1.0, conf / 100.0),
                line_key=line_key,
            )
        )
    return words


def _reconstruct(data: dict[str, Any]) -> tuple[str, float]:
    """Rebuild line-preserving text + mean word confidence from image_to_data output."""
    lines: dict[tuple[int, int, int], list[str]] = {}
    order: list[tuple[int, int, int]] = []
    confidences: list[float] = []

    for i in range(len(data["text"])):
        word = str(data["text"][i]).strip()
        if not word:
            continue
        key = (int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i]))
        if key not in lines:
            lines[key] = []
            order.append(key)
        lines[key].append(word)
        conf = float(data["conf"][i])
        if conf >= 0:
            confidences.append(conf)

    text = "\n".join(" ".join(lines[k]) for k in order)
    confidence = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0
    return text, confidence


class TesseractReader:
    """DocumentReader backed by local Tesseract OCR. No API key, no network."""

    def __init__(
        self,
        lang: str = "por",
        fallback_lang: str = "eng",
        *,
        temp_root: Path = TESSERACT_TEMP_ROOT,
        timeout: float = TESSERACT_TIMEOUT_SECONDS,
    ) -> None:
        if timeout <= 0:
            raise ValueError("Tesseract timeout must be greater than zero.")
        self._lang = lang
        self._fallback_lang = fallback_lang
        self._temp_root = temp_root
        self._timeout = timeout
        self._language_resolved = False
        self._effective_lang: str | None = None

    def _resolve_lang(self) -> str | None:
        """Prefer the configured language; fall back if its data isn't installed."""
        if self._language_resolved:
            return self._effective_lang
        try:
            available = set(pytesseract.get_languages(config=""))
        except Exception as exc:  # noqa: BLE001 — binary missing / not callable
            raise RuntimeError(
                "Tesseract OCR binary not found. Install tesseract and the 'por' "
                "language pack (Windows: winget install UB-Mannheim.TesseractOCR; "
                "Linux: apt-get install tesseract-ocr tesseract-ocr-por)."
            ) from exc
        if self._lang in available:
            self._effective_lang = self._lang
        elif self._fallback_lang in available:
            self._effective_lang = self._fallback_lang
        else:
            self._effective_lang = None  # let tesseract use its default
        self._language_resolved = True
        return self._effective_lang

    def runtime_metadata(self) -> dict[str, str]:
        """Return the exact local OCR identity used by subsequent transcriptions."""
        version = str(pytesseract.get_tesseract_version())
        effective_lang = self._resolve_lang()
        return {
            "tesseract_version": version,
            "tesseract_language": effective_lang or "default",
        }

    def read(self, page: PageArtifact, deadline: Deadline) -> TranscriptionResult:
        """Read the exact PNG artifact while respecting the sheet-wide deadline."""
        lang = self._resolve_lang()
        timeout = deadline.bounded_timeout(self._timeout, stage="Tesseract OCR")
        try:
            with Image.open(io.BytesIO(page.png_bytes)) as ocr_image:
                ocr_image.load()
                if (ocr_image.width, ocr_image.height) != (page.width, page.height):
                    raise RuntimeError("Page artifact dimensions are inconsistent.")
                with _tesseract_private_temp(self._temp_root):
                    data = pytesseract.image_to_data(
                        ocr_image,
                        lang=lang,
                        output_type=pytesseract.Output.DICT,
                        timeout=timeout,
                    )
        except RuntimeError as exc:
            if str(exc) == "Tesseract process timeout":
                raise ProcessingDeadlineExceeded(
                    "Tesseract OCR timed out; manual review is required."
                ) from None
            raise
        deadline.remaining_seconds(stage="Tesseract OCR")
        text, confidence = _reconstruct(data)
        words = _collect_words(data, page.width, page.height)
        return TranscriptionResult(
            text=text,
            confidence=confidence,
            confidence_source="tesseract",
            words=words,
            image_width=page.width,
            image_height=page.height,
        )


# Preserve the public import while callers migrate to the capability-based name.
LocalOCRVisionClient = TesseractReader
