"""M6.a: deterministic classify-stage contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.clients.base import ClassificationResult
from src.clients.mock import MockLLMClient
from src.pipeline.classify import classify
from src.schema.loader import load_config
from src.schema.state import PipelineState

CONFIG = load_config(Path("configs/controle_ocorrencias.yaml"))


def test_classify_populates_state() -> None:
    client = MockLLMClient(
        classification=ClassificationResult(
            incident_type="theft", urgency="high", sector="tech_security", confidence=0.88
        )
    )
    state = PipelineState(source_pdf=Path("x.pdf"), transcription="...furto...")
    result = classify(state, client, CONFIG)

    assert result.classification is not None
    assert result.classification.incident_type == "theft"
    assert result.classification.urgency == "high"
    assert result.classification.sector == "tech_security"
    assert result.classification.confidence == 0.88
    assert client.classify_count == 1


def test_classify_passes_taxonomy_labels() -> None:
    # The mock ignores the labels but the stage must pass the config taxonomy.
    captured: dict[str, Any] = {}

    class _SpyClient(MockLLMClient):
        def classify(self, transcription, types, urgencies, sectors):  # type: ignore[no-untyped-def]
            captured["types"] = types
            captured["urgencies"] = urgencies
            captured["sectors"] = sectors
            return super().classify(transcription, types, urgencies, sectors)

    state = PipelineState(source_pdf=Path("x.pdf"), transcription="...")
    classify(state, _SpyClient(), CONFIG)
    assert "critical" in captured["urgencies"]
    assert "theft" in captured["types"]
    assert "facilities" in captured["sectors"]


def test_classify_does_not_mutate_input() -> None:
    state = PipelineState(source_pdf=Path("x.pdf"), transcription="...")
    classify(state, MockLLMClient(), CONFIG)
    assert state.classification is None


@pytest.mark.parametrize(
    "classification",
    [
        ClassificationResult(
            incident_type="invented", urgency="high", sector="tech_security", confidence=0.9
        ),
        ClassificationResult(
            incident_type="theft", urgency="invented", sector="tech_security", confidence=0.9
        ),
        ClassificationResult(
            incident_type="theft", urgency="high", sector="invented", confidence=0.9
        ),
    ],
)
def test_classify_rejects_labels_outside_config_taxonomy(
    classification: ClassificationResult,
) -> None:
    client = MockLLMClient(classification=classification)
    state = PipelineState(source_pdf=Path("x.pdf"), transcription="...")

    with pytest.raises(ValueError, match="outside configured taxonomy"):
        classify(state, client, CONFIG)
