"""Optional, local PaddleOCR reader behind the provider-agnostic VisionClient.

The Paddle SDK is deliberately not imported at module or client-construction time.
This keeps the default Tesseract path dependency-free and prevents model provisioning
unless a caller explicitly selects this experimental reader.
"""

from __future__ import annotations

import base64
import io
from typing import Protocol

from PIL import Image
from pydantic import BaseModel, Field

from src.clients.base import TranscriptionResult


class RecognizedLine(BaseModel):
    """One line and the recognition score reported by PaddleOCR."""

    text: str
    confidence: float = Field(ge=0.0, le=1.0)


class PaddleOCREngine(Protocol):
    """Small injectable boundary around the optional third-party SDK."""

    def recognize(self, image: Image.Image) -> list[RecognizedLine]: ...


class PaddleOCRVisionClient:
    """VisionClient shell for the timeboxed PP-OCRv5 bake-off."""

    def __init__(self, engine: PaddleOCREngine | None = None) -> None:
        self._engine = engine

    def transcribe(self, image_b64: str, media_type: str = "image/png") -> TranscriptionResult:
        try:
            image_bytes = base64.b64decode(image_b64, validate=True)
            image = Image.open(io.BytesIO(image_bytes))
            image.load()
        except (OSError, ValueError) as exc:
            raise RuntimeError("PaddleOCR received invalid image data.") from exc

        if self._engine is None:
            raise RuntimeError("PaddleOCR optional engine is not initialized.")
        try:
            lines = self._engine.recognize(image)
        except Exception:  # noqa: BLE001 — third-party engine boundary
            # Do not copy the SDK exception into this message: it may contain OCR text.
            raise RuntimeError("PaddleOCR failed to process the page.") from None

        confidence = sum(line.confidence for line in lines) / len(lines) if lines else 0.0
        return TranscriptionResult(
            text="\n".join(line.text for line in lines),
            confidence=confidence,
            confidence_source="paddleocr",
            # Paddle's public OCR result exposes line regions, while WordBox promises
            # token-level geometry. Fabricating words would mislead the evidence locator.
            words=None,
            image_width=image.width,
            image_height=image.height,
        )
