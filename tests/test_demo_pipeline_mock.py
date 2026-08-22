"""The public synthetic demo (demo_pipeline_mock) yields the expected normalized model."""

from __future__ import annotations

from scripts.demo_pipeline_mock import CONFIG, OCR_INCIDENT, OCR_NO_CHANGE, SAMPLE
from src.classifier.rules import RuleBasedIncidentClassifier
from src.clients.mock import FakeDocumentReader
from src.orchestrator import run_pipeline
from src.pipeline.outputs import derive_operational_outputs
from src.schema.loader import load_config
from src.schema.state import PipelineState

_CFG = load_config(CONFIG)


def _run(text: str) -> PipelineState:
    return run_pipeline(
        SAMPLE, FakeDocumentReader(text=text), RuleBasedIncidentClassifier(), _CFG
    ).state


def test_sample_image_exists() -> None:
    assert SAMPLE.exists()


def test_incident_scenario_has_occurrence() -> None:
    state = _run(OCR_INCIDENT)
    assert state.normalized is not None
    assert state.normalized.no_occurrence is False
    assert state.normalized.shift.unit == "1"
    derived = derive_operational_outputs(state, _CFG)
    assert derived.spreadsheet_rows
    assert derived.message is not None
    assert "DIA | UNIDADE | OBJETO | DESCRIÇÃO" in derived.message


def test_no_change_scenario_is_no_occurrence() -> None:
    state = _run(OCR_NO_CHANGE)
    assert state.normalized is not None
    assert state.normalized.no_occurrence is True
