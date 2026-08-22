"""Deterministic incident-classifier fakes for tests."""

from __future__ import annotations

from src.classifier.contracts import ClassificationResult
from src.schema.config import ClassificationRule


class FakeIncidentClassifier:
    """Return one canned classification and record the reviewed content."""

    def __init__(self, classification: ClassificationResult | None = None) -> None:
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
