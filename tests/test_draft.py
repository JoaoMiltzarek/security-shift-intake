"""M6.c (DoD): the email draft is deterministic and reflects the state."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.pipeline.draft import draft, render_draft
from src.schema.loader import load_config
from src.schema.state import Classification, ExtractedField, PipelineState

CONFIG = load_config(Path("configs/htmicron_security.yaml"))


def _state(must_review: bool = False) -> PipelineState:
    return PipelineState(
        source_pdf=Path("x.pdf"),
        extracted_fields=[
            ExtractedField(name="guard_name", value="A. Souza", confidence=0.95),
            ExtractedField(
                name="shift_date", value="2026-01-15", confidence=0.3, must_review=must_review
            ),
        ],
        classification=Classification(
            incident_type="theft", urgency="high", sector="tech_security", confidence=0.88
        ),
        recipients=["tech_security", "general_support"],
        must_review_fields=["shift_date"] if must_review else [],
    )


def test_draft_contains_core_fields() -> None:
    body = render_draft(_state(), CONFIG)
    assert "tech_security, general_support" in body  # recipients
    assert "theft" in body
    assert "high" in body.lower()
    assert "A. Souza" in body
    assert "DRAFT" in body


def test_draft_marks_must_review_fields() -> None:
    body = render_draft(_state(must_review=True), CONFIG)
    assert "MUST REVIEW" in body
    assert "need review before sending" in body
    assert "shift_date" in body


def test_draft_clean_record_states_passed() -> None:
    body = render_draft(_state(must_review=False), CONFIG)
    assert "passed automated checks" in body
    assert "MUST REVIEW" not in body


def test_draft_is_deterministic() -> None:
    assert render_draft(_state(), CONFIG) == render_draft(_state(), CONFIG)


def test_draft_stage_sets_email_draft() -> None:
    result = draft(_state(), CONFIG)
    assert result.email_draft is not None
    assert "Subject:" in result.email_draft


def test_draft_requires_classification() -> None:
    with pytest.raises(ValueError, match="classification"):
        render_draft(PipelineState(source_pdf=Path("x.pdf")), CONFIG)


def test_render_draft_requires_email_template() -> None:
    # The table config declares no email_template; render_draft must refuse, not crash.
    table_cfg = load_config(Path("configs/controle_ocorrencias.yaml"))
    assert table_cfg.email_template is None
    with pytest.raises(ValueError, match="email_template"):
        render_draft(_state(), table_cfg)
