"""Stable contracts for deterministic incident classification."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from src.schema.config import ClassificationRule


class ClassificationResult(BaseModel):
    """One classification constrained by the active operational taxonomy."""

    model_config = ConfigDict(extra="forbid")

    incident_type: str
    urgency: str
    sector: str
    rule_id: str


@runtime_checkable
class IncidentClassifier(Protocol):
    """Classify reviewed text without extracting document fields."""

    def classify(
        self,
        text: str,
        rules: list[ClassificationRule],
    ) -> ClassificationResult:
        """Return labels from the supplied taxonomy dimensions."""
        ...
