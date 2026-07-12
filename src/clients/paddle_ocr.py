"""Optional, local PaddleOCR reader behind the provider-agnostic VisionClient.

The Paddle SDK is deliberately not imported at module or client-construction time.
This keeps the default Tesseract path dependency-free and prevents model provisioning
unless a caller explicitly selects this experimental reader.
"""

from __future__ import annotations

from typing import Protocol

from src.clients.base import TranscriptionResult


class PaddleOCREngine(Protocol):
    """Small injectable boundary around the optional third-party SDK."""


class PaddleOCRVisionClient:
    """VisionClient shell for the timeboxed PP-OCRv5 bake-off."""

    def __init__(self, engine: PaddleOCREngine | None = None) -> None:
        self._engine = engine

    def transcribe(self, image_b64: str, media_type: str = "image/png") -> TranscriptionResult:
        raise RuntimeError("PaddleOCR reader integration is not implemented yet.")
