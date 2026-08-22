"""Classification reads normalized occurrence content and remains advisory."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.classifier.contracts import ClassificationResult
from src.clients.mock import FakeIncidentClassifier
from src.pipeline.classify import classify
from src.schema.extraction import NormalizedIncidentModel, NormalizedOccurrence
from src.schema.loader import load_config
from src.schema.state import PipelineState

CONFIG = load_config(Path("configs/controle_ocorrencias.yaml"))


def _present(*occurrences: NormalizedOccurrence) -> PipelineState:
    return PipelineState(
        source_pdf=Path("x.pdf"),
        transcription="Furto no cabeçalho não pode influenciar a triagem.",
        normalized=NormalizedIncidentModel(
            disposition="present",
            occurrences=list(occurrences),
        ),
    )


def test_classify_populates_a_rule_suggestion() -> None:
    client = FakeIncidentClassifier(
        classification=ClassificationResult(
            incident_type="theft",
            urgency="high",
            sector="tech_security",
            rule_id="incident.theft",
        )
    )
    state = _present(NormalizedOccurrence(description="Material subtraído"))

    result = classify(state, client, CONFIG)

    assert result.classification is not None
    assert result.classification.incident_type == "theft"
    assert result.classification.source == "rule"
    assert result.classification.review_status == "suggested"
    assert result.classification.classification_rule_id == "incident.theft"
    assert client.classify_count == 1


def test_classify_passes_only_normalized_occurrence_content() -> None:
    client = FakeIncidentClassifier()
    state = _present(
        NormalizedOccurrence(
            category="Portão",
            description="Aberto",
            action="Fechado pelo vigilante",
        )
    )

    classify(state, client, CONFIG)

    assert client.last_transcription == "Portão Aberto Fechado pelo vigilante"


def test_classify_does_not_mutate_input() -> None:
    state = _present(NormalizedOccurrence(description="Rotina"))
    classify(state, FakeIncidentClassifier(), CONFIG)
    assert state.classification is None


def test_classify_skips_unknown_and_failed_content() -> None:
    client = FakeIncidentClassifier()
    unknown = PipelineState(
        source_pdf=Path("x.pdf"), normalized=NormalizedIncidentModel(disposition="unknown")
    )
    failed = _present(NormalizedOccurrence(description="Furto")).model_copy(
        update={"ocr_quality": "failed"}
    )

    assert classify(unknown, client, CONFIG).classification is None
    assert classify(failed, client, CONFIG).classification is None
    assert client.classify_count == 0


def test_confirmed_no_occurrence_derives_confirmed_routine() -> None:
    state = PipelineState(
        source_pdf=Path("x.pdf"),
        normalized=NormalizedIncidentModel(disposition="none", disposition_confirmed=True),
    )

    result = classify(state, FakeIncidentClassifier(), CONFIG)

    assert result.classification is not None
    assert result.classification.incident_type == "routine"
    assert result.classification.review_status == "confirmed"
    assert result.classification.classification_rule_id == "disposition.none"


def test_unconfirmed_no_occurrence_has_no_classification() -> None:
    state = PipelineState(
        source_pdf=Path("x.pdf"),
        normalized=NormalizedIncidentModel(disposition="none"),
    )

    assert classify(state, FakeIncidentClassifier(), CONFIG).classification is None


@pytest.mark.parametrize(
    "classification",
    [
        ClassificationResult(
            incident_type="invented",
            urgency="high",
            sector="tech_security",
            rule_id="incident.theft",
        ),
        ClassificationResult(
            incident_type="theft",
            urgency="high",
            sector="tech_security",
            rule_id="invented",
        ),
    ],
)
def test_classify_rejects_output_that_disagrees_with_config(
    classification: ClassificationResult,
) -> None:
    client = FakeIncidentClassifier(classification=classification)
    state = _present(NormalizedOccurrence(description="Furto"))

    with pytest.raises(ValueError, match="classification output"):
        classify(state, client, CONFIG)


def test_multiple_occurrences_choose_highest_urgency_then_rule_order() -> None:
    from src.classifier.rules import RuleBasedIncidentClassifier

    state = _present(
        NormalizedOccurrence(description="Alarme disparado"),
        NormalizedOccurrence(description="Furto confirmado"),
    )

    result = classify(state, RuleBasedIncidentClassifier(), CONFIG)

    assert result.classification is not None
    assert result.classification.classification_rule_id == "incident.theft"
