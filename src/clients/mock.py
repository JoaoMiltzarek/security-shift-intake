"""MockVisionClient — deterministic, offline, $0 stand-in for tests.

MOCK: this performs no model inference. It returns a canned TranscriptionResult so
pipeline tests are deterministic and cost nothing (spec §8.4, §8.8). Never present
it as working transcription functionality.
"""

from __future__ import annotations

from src.clients.base import TranscriptionResult


class MockVisionClient:
    """Returns a fixed transcription and records how it was called."""

    def __init__(self, text: str = "MOCK TRANSCRIPTION", confidence: float = 0.9) -> None:
        self._text = text
        self._confidence = confidence
        self.call_count = 0
        self.last_image_b64: str | None = None

    def transcribe(self, image_b64: str, media_type: str = "image/png") -> TranscriptionResult:
        self.call_count += 1
        self.last_image_b64 = image_b64
        return TranscriptionResult(text=self._text, confidence=self._confidence)
