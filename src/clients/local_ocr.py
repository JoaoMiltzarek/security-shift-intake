"""LocalOCRVisionClient — zero-cost, offline transcription via Tesseract OCR.

Implements VisionClient using the local Tesseract binary (no API, no network, no
cost). Returns the OCR text with **line structure preserved** (so the rule-based
extractor can anchor on labels) plus a confidence aggregated from Tesseract's
per-word scores.

HONEST LIMITATION (§4): Tesseract reads printed text well but is weak on cursive
handwriting. Low-confidence/garbled output is expected on handwritten values — the
critic flags those MUST_REVIEW and the human corrects them in the review screen.
This is the OCR + rules + human-in-the-loop design (à la ExpenseIt), not "trust the
OCR".
"""

from __future__ import annotations

import base64
import io
import os
from typing import Any

import pytesseract
from PIL import Image

from src.clients.base import TranscriptionResult, WordBox

# Real office scans are low-resolution; rasterizing them at high DPI upscales the
# noise and *hurts* Tesseract. Empirically (real folhas) OCR peaks near ~150 DPI for
# A4, so we cap the longest side before OCR — large inputs are downscaled, small
# synthetic renders are left untouched.
_MAX_OCR_LONG_SIDE = 1800

# Boxes must serve the *same* image the cockpit displays, so geometry and pixels
# share one transform. Rounding can push a fraction a hair past [0,1]; clamp that.
# Anything wildly out is a real bug — discard the word, never clamp it silently.
_CLAMP_EPS = 0.01


def downscale_for_ocr(image: Image.Image) -> Image.Image:
    """Downscale oversized scans so Tesseract reads them better; leave small ones as-is.

    Public because the cockpit persists *this exact image* (same transform) so the
    normalized word boxes line up pixel-for-pixel with what the reviewer sees.
    """
    longest = max(image.width, image.height)
    if longest <= _MAX_OCR_LONG_SIDE:
        return image
    scale = _MAX_OCR_LONG_SIDE / longest
    new_size = (round(image.width * scale), round(image.height * scale))
    return image.resize(new_size, Image.Resampling.LANCZOS)


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


class LocalOCRVisionClient:
    """VisionClient backed by local Tesseract OCR. No API key, no network."""

    def __init__(self, lang: str = "por", fallback_lang: str = "eng") -> None:
        self._lang = lang
        self._fallback_lang = fallback_lang

    def _resolve_lang(self) -> str | None:
        """Prefer the configured language; fall back if its data isn't installed."""
        try:
            available = set(pytesseract.get_languages(config=""))
        except Exception as exc:  # noqa: BLE001 — binary missing / not callable
            raise RuntimeError(
                "Tesseract OCR binary not found. Install tesseract and the 'por' "
                "language pack (Windows: winget install UB-Mannheim.TesseractOCR; "
                "Linux: apt-get install tesseract-ocr tesseract-ocr-por)."
            ) from exc
        if self._lang in available:
            return self._lang
        if self._fallback_lang in available:
            return self._fallback_lang
        return None  # let tesseract use its default

    def transcribe(self, image_b64: str, media_type: str = "image/png") -> TranscriptionResult:
        lang = self._resolve_lang()
        image = Image.open(io.BytesIO(base64.standard_b64decode(image_b64)))
        ocr_image = downscale_for_ocr(image)
        data = pytesseract.image_to_data(
            ocr_image, lang=lang, output_type=pytesseract.Output.DICT
        )
        text, confidence = _reconstruct(data)
        words = _collect_words(data, ocr_image.width, ocr_image.height)
        return TranscriptionResult(
            text=text,
            confidence=confidence,
            confidence_source="tesseract",
            words=words,
            image_width=ocr_image.width,
            image_height=ocr_image.height,
        )
