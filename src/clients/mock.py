"""MockVisionClient — deterministic, offline, $0 stand-in for tests.

MOCK: this performs no model inference. It returns a canned TranscriptionResult so
pipeline tests are deterministic and cost nothing (spec §8.4, §8.8). Never present
it as working transcription functionality.
"""

from __future__ import annotations

from src.clients.base import ExtractedFieldRaw, TranscriptionResult


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


class MockLLMClient:
    """Returns canned extracted fields and records how it was called.

    MOCK: no model inference. Configure with a list of ExtractedFieldRaw; only the
    requested field names are returned (missing ones come back as null/0.0).
    """

    def __init__(self, fields: list[ExtractedFieldRaw] | None = None) -> None:
        self._by_name = {f.name: f for f in (fields or [])}
        self.call_count = 0
        self.last_transcription: str | None = None

    def extract_fields(self, transcription: str, field_names: list[str]) -> list[ExtractedFieldRaw]:
        self.call_count += 1
        self.last_transcription = transcription
        return [
            self._by_name.get(name, ExtractedFieldRaw(name=name, value=None, confidence=0.0))
            for name in field_names
        ]
