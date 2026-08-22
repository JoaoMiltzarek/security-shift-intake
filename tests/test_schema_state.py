"""M1.c: unit tests for PipelineState and related models."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.api.readiness import ReadinessBlockerCode, evaluate_readiness
from src.schema.extraction import NormalizedIncidentModel
from src.schema.state import (
    ApprovalStatus,
    Classification,
    ExtractedField,
    PipelineState,
    UnsupportedPipelineStateVersionError,
)

V1_STATE_FIXTURE = Path(__file__).parent / "fixtures" / "pipeline_state_v1_0.json"
V1_RETIRED_FIELDS = {
    "image_paths",
    "page_image_paths",
    "reconcile_results",
    "recipients",
    "email_draft",
    "spreadsheet_rows",
    "approval_status",
    "audit_log",
}


def test_initial_state_defaults() -> None:
    state = PipelineState(source_pdf=Path("report.pdf"))
    assert state.schema_version == "2.0"
    assert state.is_legacy is False
    assert state.legacy_evidence is None
    assert state.page_artifacts == []
    assert state.transcription is None
    assert state.extracted_fields == []
    assert state.must_review_fields == []
    assert state.classification is None


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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source", "model"),
        ("status", "trusted"),
        ("evidence_method", "fuzzy"),
    ],
)
def test_extracted_field_rejects_unknown_provenance(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        ExtractedField.model_validate({"name": "unidade", "confidence": 0.5, field: value})


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
        source="rule",
        review_status="suggested",
        classification_rule_id="classification.default",
    )
    assert c.incident_type == "routine"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "incident_type": "theft",
            "urgency": "high",
            "sector": "tech_security",
            "source": "rule",
            "review_status": "suggested",
        },
        {
            "incident_type": "theft",
            "urgency": "high",
            "sector": "tech_security",
            "source": "human",
            "review_status": "suggested",
        },
        {
            "incident_type": "theft",
            "urgency": "high",
            "sector": "tech_security",
            "source": "human",
            "review_status": "confirmed",
            "classification_rule_id": "incident.theft",
        },
    ],
)
def test_classification_rejects_contradictory_provenance(payload: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        Classification.model_validate(payload)


def test_state_with_populated_fields() -> None:
    state = PipelineState(
        source_pdf=Path("scan.pdf"),
        transcription="Guard: João. Date: 2026-01-15. No incident.",
        transcription_confidence=0.91,
        normalized=NormalizedIncidentModel(
            disposition="none",
            disposition_confirmed=True,
        ),
        extracted_fields=[
            ExtractedField(name="guard_name", value="João", confidence=0.91),
        ],
        classification=Classification(
            incident_type="routine",
            urgency="low",
            sector="general_support",
            source="rule",
            review_status="confirmed",
            classification_rule_id="disposition.none",
        ),
    )
    assert len(state.extracted_fields) == 1


def test_v2_classification_requires_normalized_state() -> None:
    with pytest.raises(ValidationError, match="requires normalized"):
        PipelineState(
            source_pdf=Path("scan.pdf"),
            classification=Classification(
                incident_type="routine",
                urgency="low",
                sector="general_support",
                source="rule",
                review_status="suggested",
                classification_rule_id="classification.default",
            ),
        )


def test_v2_unknown_disposition_rejects_classification() -> None:
    with pytest.raises(ValidationError, match="unknown disposition"):
        PipelineState(
            source_pdf=Path("scan.pdf"),
            normalized=NormalizedIncidentModel(disposition="unknown"),
            classification=Classification(
                incident_type="routine",
                urgency="low",
                sector="general_support",
                source="rule",
                review_status="suggested",
                classification_rule_id="classification.default",
            ),
        )


def test_v2_no_change_requires_the_canonical_classification() -> None:
    with pytest.raises(ValidationError, match="disposition.none"):
        PipelineState(
            source_pdf=Path("scan.pdf"),
            normalized=NormalizedIncidentModel(
                disposition="none",
                disposition_confirmed=True,
            ),
            classification=Classification(
                incident_type="safety",
                urgency="critical",
                sector="facilities",
                source="human",
                review_status="confirmed",
            ),
        )


def test_approval_status_values() -> None:
    assert ApprovalStatus.PENDING == "pending"
    assert ApprovalStatus.APPROVED == "approved"
    assert ApprovalStatus.REJECTED == "rejected"
    assert ApprovalStatus.SIMULATED == "simulated"


def test_persisted_unversioned_state_is_readable_but_marked_legacy() -> None:
    state = PipelineState.from_persisted_json('{"source_pdf":"report.pdf"}')

    assert state.schema_version == "2.0"
    assert state.legacy_source_version == "unversioned"
    assert state.is_legacy is True


def test_v2_state_rejects_loose_image_paths() -> None:
    with pytest.raises(ValidationError, match="image_paths"):
        PipelineState.model_validate(
            {
                "schema_version": "2.0",
                "source_pdf": "report.pdf",
                "image_paths": ["private/unsafe-source.png"],
            }
        )


def test_legacy_paths_are_reduced_to_untrusted_shape_metadata() -> None:
    state = PipelineState.from_persisted_json(
        """{
            "source_pdf": "report.pdf",
            "image_paths": ["private/unsafe-source.png"],
            "page_image_paths": ["unsafe/page_0.png", "unsafe/page_1.png"]
        }"""
    )

    assert state.legacy_evidence is not None
    assert state.legacy_evidence.source_image_count == 1
    assert state.legacy_evidence.stored_page_count == 2
    assert state.page_artifacts == []
    assert state.exceeds_v1_page_scope()
    persisted = state.model_dump_json()
    assert "unsafe-source" not in persisted
    assert "unsafe/page_0" not in persisted


def test_legacy_marker_survives_a_new_snapshot() -> None:
    state = PipelineState.from_persisted_json('{"source_pdf":"report.pdf"}')
    restored = PipelineState.from_persisted_json(state.model_dump_json())

    assert restored.legacy_source_version == "unversioned"


def test_complete_v1_snapshot_is_visible_but_operationally_blocked() -> None:
    payload = V1_STATE_FIXTURE.read_text(encoding="utf-8")

    state = PipelineState.from_persisted_json(payload)

    assert state.legacy_source_version == "unversioned"
    assert state.is_legacy
    assert state.transcription is not None and "Alarm test" in state.transcription
    assert state.raw_extraction is not None
    assert state.normalized is not None and len(state.normalized.occurrences) == 1
    assert state.classification is not None
    assert state.classification.classification_rule_id == "legacy.unverified"
    assert state.legacy_evidence is not None
    assert state.legacy_evidence.source_image_count == 1
    assert state.legacy_evidence.stored_page_count == 1
    assert state.page_artifacts == []
    assert V1_RETIRED_FIELDS.isdisjoint(state.model_dump())

    readiness = evaluate_readiness(state, None)
    assert not readiness.approvable
    assert not readiness.exportable
    assert not readiness.simulatable
    assert readiness.blocker(ReadinessBlockerCode.EVIDENCE_CHANGED) is not None


def test_complete_v1_shape_with_future_version_is_rejected() -> None:
    payload = json.loads(V1_STATE_FIXTURE.read_text(encoding="utf-8"))
    payload["schema_version"] = "3.0"

    with pytest.raises(UnsupportedPipelineStateVersionError, match="unsupported"):
        PipelineState.from_persisted_json(json.dumps(payload))


def test_pipeline_state_rejects_partial_config_identity() -> None:
    with pytest.raises(ValidationError, match="report_type and config_sha256"):
        PipelineState(source_pdf=Path("report.pdf"), report_type="controle_ocorrencias")


@pytest.mark.parametrize("version", ["3.0", "future", 3])
def test_persisted_state_rejects_unknown_schema_version(version: object) -> None:
    payload = f'{{"schema_version": {version!r}, "source_pdf": "report.pdf"}}'
    if isinstance(version, str):
        payload = payload.replace(f"'{version}'", f'"{version}"')

    with pytest.raises(UnsupportedPipelineStateVersionError, match="unsupported"):
        PipelineState.from_persisted_json(payload)
