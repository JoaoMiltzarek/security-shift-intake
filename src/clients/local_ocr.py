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
from typing import Any

import pytesseract
from PIL import Image

from src.clients.base import TranscriptionResult


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
        data = pytesseract.image_to_data(
            image, lang=lang, output_type=pytesseract.Output.DICT
        )
        text, confidence = _reconstruct(data)
        return TranscriptionResult(text=text, confidence=confidence)
