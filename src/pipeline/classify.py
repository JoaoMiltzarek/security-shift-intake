"""Advisory classification over normalized occurrence content only."""

from __future__ import annotations

from src.classifier.contracts import ClassificationResult, IncidentClassifier
from src.schema.config import ReportConfig
from src.schema.extraction import NormalizedOccurrence
from src.schema.state import ClassificationDecision, PipelineState

_URGENCY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_NONE_RULE_ID = "disposition.none"


def occurrence_text(occurrence: NormalizedOccurrence) -> str:
    """Build the only text surface classification is allowed to inspect."""
    return " ".join(
        value.strip()
        for value in (occurrence.category, occurrence.description, occurrence.action)
        if value and value.strip()
    )


def _validated_result(result: ClassificationResult, config: ReportConfig) -> None:
    rules = {rule.id: rule for rule in config.classification.rules}
    rule = rules.get(result.rule_id)
    if rule is None:
        raise ValueError("classification output references an unknown rule id")
    if (result.incident_type, result.urgency, result.sector) != (
        rule.type,
        rule.urgency,
        rule.sector,
    ):
        raise ValueError("classification output does not match its configured rule")


def classify(
    state: PipelineState,
    client: IncidentClassifier,
    config: ReportConfig,
) -> PipelineState:
    """Store one deterministic suggestion, or no decision for blocked content."""
    normalized = state.normalized
    if normalized is None or normalized.disposition == "unknown" or state.ocr_quality == "failed":
        return state.model_copy(update={"classification": None})
    if normalized.disposition == "none":
        if not normalized.disposition_confirmed:
            return state.model_copy(update={"classification": None})
        return state.model_copy(
            update={
                "classification": ClassificationDecision(
                    incident_type="routine",
                    urgency="low",
                    sector="general_support",
                    source="rule",
                    review_status="confirmed",
                    classification_rule_id=_NONE_RULE_ID,
                )
            }
        )

    rule_order = {rule.id: index for index, rule in enumerate(config.classification.rules)}
    candidates: list[tuple[int, int, int, ClassificationResult]] = []
    for occurrence_index, occurrence in enumerate(normalized.occurrences):
        result = client.classify(occurrence_text(occurrence), config.classification.rules)
        _validated_result(result, config)
        candidates.append(
            (
                _URGENCY_RANK.get(result.urgency, -1),
                -rule_order[result.rule_id],
                -occurrence_index,
                result,
            )
        )
    if not candidates:
        return state.model_copy(update={"classification": None})
    selected = max(candidates, key=lambda candidate: candidate[:3])[3]
    return state.model_copy(
        update={
            "classification": ClassificationDecision(
                incident_type=selected.incident_type,
                urgency=selected.urgency,
                sector=selected.sector,
                source="rule",
                review_status="suggested",
                classification_rule_id=selected.rule_id,
            )
        }
    )
