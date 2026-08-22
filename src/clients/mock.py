"""Deterministic, offline document-reader fake for tests.

The reader fake performs no OCR. It returns a canned ``TranscriptionResult`` so
pipeline tests are deterministic and cost nothing (spec §8.4, §8.8). Never present
it as working transcription functionality.
"""

from __future__ import annotations

from src.clients.base import TranscriptionResult
from src.pipeline.ingest import Deadline, PageArtifact


class FakeDocumentReader:
    """Returns a fixed transcription and records how it was called."""

    def __init__(self, text: str = "MOCK TRANSCRIPTION", confidence: float = 0.9) -> None:
        self._text = text
        self._confidence = confidence
        self.call_count = 0
        self.last_page_sha256: str | None = None

    def read(self, page: PageArtifact, deadline: Deadline) -> TranscriptionResult:
        """Return canned text while exercising the production page/deadline contract."""
        deadline.remaining_seconds(stage="mock document reading")
        self.call_count += 1
        self.last_page_sha256 = page.sha256
        return TranscriptionResult(
            text=self._text, confidence=self._confidence, confidence_source="mock"
        )


# Temporary compatibility for the pre-checkpoint evaluation/UI branches. Product code
# and current tests use the role-based name above; the alias can disappear with those
# historical consumers after the Linux corpus series lands.
MockVisionClient = FakeDocumentReader
