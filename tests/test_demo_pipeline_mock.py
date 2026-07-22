"""The public synthetic demo (demo_pipeline_mock) yields the expected normalized model."""

from __future__ import annotations

from scripts.demo_pipeline_mock import CONFIG, OCR_INCIDENT, OCR_NO_CHANGE, SAMPLE
from src.clients.local_rules import RuleBasedLLMClient
from src.clients.mock import MockVisionClient
from src.orchestrator import run_pipeline
from src.schema.loader import load_config

_CFG = load_config(CONFIG)


def _run(text: str) -> object:
    return run_pipeline(SAMPLE, MockVisionClient(text=text), RuleBasedLLMClient(_CFG), _CFG).state


def test_sample_image_exists() -> None:
    assert SAMPLE.exists()


def test_incident_scenario_has_occurrence() -> None:
    state = _run(OCR_INCIDENT)
    assert state.normalized is not None
    assert state.normalized.no_occurrence is False
    assert state.normalized.shift.unit == "1"
    assert state.spreadsheet_rows  # Output 1 (planilha) populated
    assert state.email_draft is not None
    assert "DIA | UNIDADE | OBJETO | DESCRIÇÃO" in state.email_draft  # Output 2 (copy-ready)


def test_no_change_scenario_is_no_occurrence() -> None:
    state = _run(OCR_NO_CHANGE)
    assert state.normalized is not None
    assert state.normalized.no_occurrence is True
