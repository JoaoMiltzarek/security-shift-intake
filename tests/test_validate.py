"""M5.b (DoD): critic flags low-confidence and schema-invalid fields as MUST_REVIEW.

Covers the three required cases — a clean record, a low-confidence field, and a
schema-invalid field — plus required-missing and optional-blank.
"""

from __future__ import annotations

from pathlib import Path

from src.pipeline.validate import validate
from src.schema.loader import load_config
from src.schema.state import ExtractedField, PipelineState

CONFIG = load_config(Path("configs/htmicron_security.yaml"))


def _clean_fields(confidence: float = 0.95) -> list[ExtractedField]:
    """A fully valid, high-confidence extraction for every configured field."""
    values = {
        "shift_date": "2026-01-15",
        "guard_name": "A. Souza",
        "post": "Portaria 1",
        "shift_period": "day",
        "incident_occurred": "nao",
        "incident_description": None,  # optional, blank is fine
    }
    return [
        ExtractedField(name=name, value=values[name], confidence=confidence)
        for name in (f.name for f in CONFIG.fields)
    ]


def _state(fields: list[ExtractedField]) -> PipelineState:
    return PipelineState(source_pdf=Path("x.pdf"), extracted_fields=fields)


# ---------------------------------------------------------------------------
# Clean record -> no flags
# ---------------------------------------------------------------------------


def test_clean_record_has_no_flags() -> None:
    result = validate(_state(_clean_fields()), CONFIG)
    assert result.must_review_fields == []
    assert result.validation_errors == []
    assert all(not f.must_review for f in result.extracted_fields)


def test_scalar_critic_sets_status_and_leaves_source_none() -> None:
    result = validate(_state(_clean_fields()), CONFIG)
    guard = next(f for f in result.extracted_fields if f.name == "guard_name")
    assert guard.status == "accepted"
    assert guard.source is None  # no AuditedField behind the scalar path
    desc = next(f for f in result.extracted_fields if f.name == "incident_description")
    assert desc.status == "missing"  # optional + blank: status reflects it, not flagged


# ---------------------------------------------------------------------------
# Low-confidence field -> flagged, but not a schema error
# ---------------------------------------------------------------------------


def test_low_confidence_field_is_flagged() -> None:
    fields = _clean_fields()
    for f in fields:
        if f.name == "guard_name":
            object.__setattr__(f, "confidence", 0.30)  # below threshold, value still valid
    result = validate(_state(fields), CONFIG)

    assert "guard_name" in result.must_review_fields
    guard = next(f for f in result.extracted_fields if f.name == "guard_name")
    assert guard.must_review is True
    assert result.validation_errors == []  # low confidence is not a schema error


# ---------------------------------------------------------------------------
# Schema-invalid field -> flagged with a validation error
# ---------------------------------------------------------------------------


def test_invalid_enum_value_is_flagged() -> None:
    fields = _clean_fields()
    for f in fields:
        if f.name == "shift_period":
            object.__setattr__(f, "value", "afternoon")  # not in [day, night]
    result = validate(_state(fields), CONFIG)

    assert "shift_period" in result.must_review_fields
    assert any("shift_period" in e for e in result.validation_errors)


def test_invalid_date_is_flagged() -> None:
    fields = _clean_fields()
    for f in fields:
        if f.name == "shift_date":
            object.__setattr__(f, "value", "31-31-2026")
    result = validate(_state(fields), CONFIG)
    assert "shift_date" in result.must_review_fields
    assert any("shift_date" in e for e in result.validation_errors)


def test_invalid_bool_is_flagged() -> None:
    fields = _clean_fields()
    for f in fields:
        if f.name == "incident_occurred":
            object.__setattr__(f, "value", "maybe")
    result = validate(_state(fields), CONFIG)
    assert "incident_occurred" in result.must_review_fields


# ---------------------------------------------------------------------------
# Required-missing and optional-blank
# ---------------------------------------------------------------------------


def test_required_missing_is_flagged() -> None:
    fields = _clean_fields()
    for f in fields:
        if f.name == "guard_name":
            object.__setattr__(f, "value", None)
    result = validate(_state(fields), CONFIG)
    assert "guard_name" in result.must_review_fields
    assert any("guard_name" in e and "missing" in e for e in result.validation_errors)


def test_optional_blank_is_not_flagged() -> None:
    # incident_description is optional; blank must not flag.
    result = validate(_state(_clean_fields()), CONFIG)
    assert "incident_description" not in result.must_review_fields


def test_accepts_brazilian_date_format() -> None:
    fields = _clean_fields()
    for f in fields:
        if f.name == "shift_date":
            object.__setattr__(f, "value", "15/01/2026")  # dd/mm/yyyy
    result = validate(_state(fields), CONFIG)
    assert "shift_date" not in result.must_review_fields


def test_validate_does_not_mutate_input() -> None:
    state = _state(_clean_fields(confidence=0.30))  # everything low-confidence
    validate(state, CONFIG)
    assert state.must_review_fields == []  # original untouched
