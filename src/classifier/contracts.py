"""Stable contracts for deterministic incident classification."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ClassificationResult(BaseModel):
    """One classification constrained by the active operational taxonomy."""

    incident_type: str
    urgency: str
    sector: str
    confidence: float = Field(ge=0.0, le=1.0)


@runtime_checkable
class IncidentClassifier(Protocol):
    """Classify reviewed text without extracting document fields."""

    def classify(
        self,
        text: str,
        types: list[str],
        urgencies: list[str],
        sectors: list[str],
    ) -> ClassificationResult:
        """Return labels from the supplied taxonomy dimensions."""
        ...
