"""M6.b (DoD): deterministic routing applies the YAML rules correctly."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.pipeline.route import route, select_recipients
from src.schema.loader import load_config
from src.schema.state import Classification, PipelineState

CONFIG = load_config(Path("configs/controle_ocorrencias.yaml"))


def _cls(incident_type: str, urgency: str, sector: str) -> Classification:
    return Classification(
        incident_type=incident_type, urgency=urgency, sector=sector, confidence=0.9
    )


def test_critical_urgency_routes_to_oncall() -> None:
    r = select_recipients(_cls("safety", "critical", "facilities"), CONFIG)
    assert r == ["tech_security_oncall", "general_support"]


def test_theft_routes_to_tech_and_support() -> None:
    r = select_recipients(_cls("theft", "high", "tech_security"), CONFIG)
    assert r == ["tech_security", "general_support"]


def test_equipment_routes_to_facilities() -> None:
    r = select_recipients(_cls("equipment", "medium", "facilities"), CONFIG)
    assert r == ["facilities"]


def test_access_violation_routes_to_tech_security() -> None:
    r = select_recipients(_cls("access_violation", "medium", "tech_security"), CONFIG)
    assert r == ["tech_security"]


def test_default_routes_to_general_support() -> None:
    r = select_recipients(_cls("routine", "low", "general_support"), CONFIG)
    assert r == ["general_support"]


def test_critical_takes_precedence_over_theft() -> None:
    # critical rule is listed first -> wins over the theft rule.
    r = select_recipients(_cls("theft", "critical", "tech_security"), CONFIG)
    assert r == ["tech_security_oncall", "general_support"]


def test_routing_is_deterministic() -> None:
    cls = _cls("equipment", "low", "facilities")
    assert select_recipients(cls, CONFIG) == select_recipients(cls, CONFIG)


def test_route_stage_sets_recipients() -> None:
    state = PipelineState(
        source_pdf=Path("x.pdf"),
        classification=_cls("theft", "high", "tech_security"),
    )
    result = route(state, CONFIG)
    assert result.recipients == ["tech_security", "general_support"]


def test_route_requires_classification() -> None:
    with pytest.raises(ValueError, match="classification"):
        route(PipelineState(source_pdf=Path("x.pdf")), CONFIG)
