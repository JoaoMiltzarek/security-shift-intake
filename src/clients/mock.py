"""Deterministic, offline reader and classifier fakes for tests.

MOCK: this performs no model inference. It returns a canned TranscriptionResult so
pipeline tests are deterministic and cost nothing (spec §8.4, §8.8). Never present
it as working transcription functionality.
"""

from __future__ import annotations

from src.classifier.contracts import ClassificationResult
from src.clients.base import TranscriptionResult
from src.pipeline.ingest import Deadline, PageArtifact
from src.schema.config import ClassificationRule


class MockVisionClient:
    """Returns a fixed transcription and records how it was called."""

    def __init__(self, text: str = "MOCK TRANSCRIPTION", confidence: float = 0.9) -> None:
        self._text = text
        self._confidence = confidence
        self.call_count = 0
        self.last_image_b64: str | None = None
        self.last_page_sha256: str | None = None

    def read(self, page: PageArtifact, deadline: Deadline) -> TranscriptionResult:
        """Return canned text while exercising the production page/deadline contract."""
        deadline.remaining_seconds(stage="mock document reading")
        self.call_count += 1
        self.last_page_sha256 = page.sha256
        return TranscriptionResult(
            text=self._text, confidence=self._confidence, confidence_source="mock"
        )

    def transcribe(self, image_b64: str, media_type: str = "image/png") -> TranscriptionResult:
        """Legacy helper for historical adapter unit tests outside product orchestration."""
        self.call_count += 1
        self.last_image_b64 = image_b64
        return TranscriptionResult(
            text=self._text, confidence=self._confidence, confidence_source="mock"
        )


class FakeIncidentClassifier:
    """Return one canned classification and record the reviewed content."""

    def __init__(
        self,
        classification: ClassificationResult | None = None,
    ) -> None:
        self._classification = classification or ClassificationResult(
            incident_type="other",
            urgency="medium",
            sector="general_support",
            rule_id="incident.other",
        )
        self.classify_count = 0
        self.last_transcription: str | None = None

    def classify(
        self,
        transcription: str,
        rules: list[ClassificationRule],
    ) -> ClassificationResult:
        self.classify_count += 1
        self.last_transcription = transcription
        return self._classification
