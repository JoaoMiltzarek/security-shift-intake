"""RuleBasedLLMClient — zero-cost, deterministic extraction + classification.

Implements LLMClient with **no model and no API**:
- `extract_fields`: anchors on each field's printed label (config `ocr_aliases`) in
  the line-preserving OCR text, takes the value after the label, normalizes by type.
- `classify`: deterministic — incident type via the keyword baseline, sector/urgency
  via explicit auditable maps.

Design rule (user requirement): **never guess.** A found value is given a modest
confidence (below the review threshold) so the critic flags it MUST_REVIEW and the
human verifies/corrects it; a value not found is `None` (confidence 0.0) and flagged
as missing. Pre-fill to save typing, but the human confirms — like ExpenseIt.
"""

from __future__ import annotations

from src.classifier.model import keyword_predict
from src.clients.base import ClassificationResult, ExtractedFieldRaw
from src.schema.config import FieldSchema, ReportConfig

# Found-but-OCR'd values sit just below the critic threshold (0.70) so they are
# always surfaced for human verification rather than trusted blindly.
FOUND_CONFIDENCE = 0.65
CLASSIFY_CONFIDENCE = 0.60

# Portuguese surface terms → canonical enum values.
_ENUM_NORMALISE: dict[str, str] = {"dia": "day", "noite": "night", "day": "day", "night": "night"}

# Deterministic, auditable maps (independent of the synthetic generator).
_SECTOR_BY_TYPE: dict[str, str] = {
    "routine": "general_support",
    "access_violation": "tech_security",
    "equipment": "facilities",
    "safety": "facilities",
    "theft": "tech_security",
    "other": "general_support",
}
_URGENCY_BY_TYPE: dict[str, str] = {
    "routine": "low",
    "equipment": "medium",
    "access_violation": "medium",
    "safety": "high",
    "theft": "high",
    "other": "medium",
}


class RuleBasedLLMClient:
    """LLMClient with deterministic, offline extraction and classification."""

    def __init__(self, config: ReportConfig) -> None:
        self._fields = {f.name: f for f in config.fields}

    def _find_value(self, lines: list[str], field: FieldSchema) -> str | None:
        """Return the text after the field's label on the matching line, else None."""
        aliases = field.ocr_aliases or [field.name]
        for alias in aliases:
            needle = alias.rstrip(":").lower()
            for line in lines:
                idx = line.lower().find(needle)
                if idx >= 0:
                    value = line[idx + len(needle):].lstrip(" :\t").strip()
                    if value:
                        return value
        return None

    def _normalise(self, field: FieldSchema, value: str) -> str:
        if field.type == "enum":
            allowed = {v.lower() for v in (field.values or [])}
            if value.lower() not in allowed:
                return _ENUM_NORMALISE.get(value.lower(), value)
        return value

    def extract_fields(self, transcription: str, field_names: list[str]) -> list[ExtractedFieldRaw]:
        lines = transcription.splitlines()
        results: list[ExtractedFieldRaw] = []
        for name in field_names:
            field = self._fields.get(name)
            value = self._find_value(lines, field) if field is not None else None
            if not value:
                results.append(ExtractedFieldRaw(name=name, value=None, confidence=0.0))
            else:
                normalised = self._normalise(field, value) if field else value
                results.append(
                    ExtractedFieldRaw(name=name, value=normalised, confidence=FOUND_CONFIDENCE)
                )
        return results

    def classify(
        self,
        transcription: str,
        types: list[str],
        urgencies: list[str],
        sectors: list[str],
    ) -> ClassificationResult:
        incident_type = keyword_predict([transcription])[0]
        return ClassificationResult(
            incident_type=incident_type,
            urgency=_URGENCY_BY_TYPE.get(incident_type, "medium"),
            sector=_SECTOR_BY_TYPE.get(incident_type, "general_support"),
            confidence=CLASSIFY_CONFIDENCE,
        )
