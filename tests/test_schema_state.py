"""M1.c: unit tests for PipelineState and related models."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.schema.state import ApprovalStatus, Classification, ExtractedField, PipelineState


def test_initial_state_defaults() -> None:
    state = PipelineState(source_pdf=Path("report.pdf"))
    assert state.image_paths == []
    assert state.transcription is None
    assert state.extracted_fields == []
    assert state.must_review_fields == []
    assert state.classification is None
    assert state.email_draft is None
    assert state.approval_status == ApprovalStatus.PENDING
    assert state.audit_log == []


def test_extracted_field_valid() -> None:
    f = ExtractedField(name="guard_name", value="Guard_042", confidence=0.95)
    assert f.must_review is False


def test_extracted_field_source_status_default_none() -> None:
    f = ExtractedField(name="guard_name", value="Guard_042", confidence=0.95)
    assert f.source is None
    assert f.status is None


def test_extracted_field_source_status_set() -> None:
    f = ExtractedField(
        name="unidade", value="1", confidence=0.65, source="rule", status="must_review"
    )
    assert f.source == "rule"
    assert f.status == "must_review"


def test_extracted_field_low_confidence_flag() -> None:
    f = ExtractedField(name="shift_date", value="2026-01-15", confidence=0.45, must_review=True)
    assert f.must_review is True


def test_extracted_field_confidence_bounds() -> None:
    with pytest.raises(ValidationError):
        ExtractedField(name="x", confidence=1.5)
    with pytest.raises(ValidationError):
        ExtractedField(name="x", confidence=-0.1)


def test_classification_valid() -> None:
    c = Classification(
        incident_type="routine",
        urgency="low",
        sector="general_support",
        confidence=0.88,
    )
    assert c.incident_type == "routine"


def test_state_with_populated_fields() -> None:
    state = PipelineState(
        source_pdf=Path("scan.pdf"),
        transcription="Guard: João. Date: 2026-01-15. No incident.",
        transcription_confidence=0.91,
        extracted_fields=[
            ExtractedField(name="guard_name", value="João", confidence=0.91),
        ],
        classification=Classification(
            incident_type="routine", urgency="low", sector="general_support", confidence=0.92
        ),
        recipients=["general_support"],
        email_draft="Subject: Shift report ...",
        approval_status=ApprovalStatus.APPROVED,
    )
    assert state.approval_status == ApprovalStatus.APPROVED
    assert len(state.extracted_fields) == 1


def test_approval_status_values() -> None:
    assert ApprovalStatus.PENDING == "pending"
    assert ApprovalStatus.APPROVED == "approved"
    assert ApprovalStatus.REJECTED == "rejected"
