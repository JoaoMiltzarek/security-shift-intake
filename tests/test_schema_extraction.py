"""Tests for the table-extraction models (src/schema/extraction.py).

One scenario per test. Models are pure data contracts (R1/R2).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.schema.extraction import (
    AuditedField,
    NormalizedIncidentModel,
    NormalizedOccurrence,
    NormalizedShift,
    RawDocumentExtraction,
    RawRow,
)
from src.schema.state import PipelineState


def test_audited_field_defaults_to_missing() -> None:
    f = AuditedField()
    assert f.value is None
    assert f.status == "missing"
    assert f.source == "ocr"
    assert f.confidence == 0.0


def test_audited_field_accepts_list_value() -> None:
    f = AuditedField(value=["A", "B"], confidence=0.3, source="rule", status="must_review")
    assert f.value == ["A", "B"]


def test_audited_field_rejects_bad_status() -> None:
    with pytest.raises(ValidationError):
        AuditedField(status="weird")  # type: ignore[arg-type]


def test_audited_field_confidence_bounds() -> None:
    with pytest.raises(ValidationError):
        AuditedField(confidence=1.5)


def test_raw_row_defaults_all_cells_missing() -> None:
    row = RawRow()
    assert row.item.status == "missing"
    assert row.sem_alteracao is False


def test_raw_document_minimal() -> None:
    raw = RawDocumentExtraction(report_type="controle_ocorrencias")
    assert raw.schema_version == "1.0"
    assert raw.header.vigilantes.status == "missing"
    assert raw.rows == []


def test_raw_document_roundtrip() -> None:
    raw = RawDocumentExtraction(
        report_type="controle_ocorrencias",
        rows=[RawRow(sem_alteracao=True)],
    )
    again = RawDocumentExtraction.model_validate_json(raw.model_dump_json())
    assert again.rows[0].sem_alteracao is True


def test_normalized_no_occurrence() -> None:
    m = NormalizedIncidentModel(shift=NormalizedShift(unit="Posto"), no_occurrence=True)
    assert m.no_occurrence is True
    assert m.occurrences == []


def test_normalized_with_occurrence() -> None:
    occ = NormalizedOccurrence(
        category="Acesso", entry_time="x", exit_time="y", resolved=True, needs_review=True
    )
    m = NormalizedIncidentModel(occurrences=[occ])
    assert m.occurrences[0].resolved is True
    assert m.occurrences[0].needs_review is True


# --- Contratos F2.A1 (SSI-1005): disposição segura e compatibilidade legada ---


@pytest.mark.xfail(strict=True, reason="F2.A1: modelo normalizado deve iniciar como unknown")
def test_normalized_defaults_to_safe_unknown() -> None:
    model = NormalizedIncidentModel()

    assert model.schema_version == "1.1"
    assert model.disposition == "unknown"
    assert model.no_occurrence is False


@pytest.mark.xfail(strict=True, reason="F2.A1: none deve derivar no_occurrence=True")
def test_normalized_none_derives_compatibility_flag() -> None:
    model = NormalizedIncidentModel(disposition="none")

    assert model.no_occurrence is True


@pytest.mark.xfail(strict=True, reason="F2.A1: ocorrências legadas devem inferir present")
def test_legacy_occurrences_infer_present() -> None:
    model = NormalizedIncidentModel(
        occurrences=[NormalizedOccurrence(description="Ocorrência confirmada.")]
    )

    assert model.disposition == "present"
    assert model.no_occurrence is False


@pytest.mark.xfail(strict=True, reason="F2.A1: vazio legado deve reabrir como unknown")
def test_legacy_empty_payload_defaults_to_unknown() -> None:
    model = NormalizedIncidentModel.model_validate(
        {"schema_version": "1.0", "no_occurrence": True, "occurrences": []}
    )

    assert model.disposition == "unknown"
    assert model.no_occurrence is False


@pytest.mark.xfail(strict=True, reason="F2.A1: flag legada não pode sobrescrever disposição")
def test_compatibility_flag_cannot_override_disposition() -> None:
    model = NormalizedIncidentModel(disposition="unknown")
    copied = model.model_copy(update={"no_occurrence": True})

    assert copied.disposition == "unknown"
    assert copied.no_occurrence is False


@pytest.mark.xfail(strict=True, reason="F2.A1: disposição deve sobreviver ao roundtrip JSON")
def test_normalized_roundtrip_preserves_disposition() -> None:
    model = NormalizedIncidentModel(disposition="none")
    restored = NormalizedIncidentModel.model_validate_json(model.model_dump_json())

    assert restored.disposition == "none"
    assert restored.no_occurrence is True


@pytest.mark.xfail(strict=True, reason="F2.A1: dump deve expor flag derivada compatível")
def test_normalized_dump_includes_derived_compatibility_flag() -> None:
    dumped = NormalizedIncidentModel(disposition="unknown").model_dump()

    assert dumped["disposition"] == "unknown"
    assert dumped["no_occurrence"] is False


@pytest.mark.xfail(strict=True, reason="F2.A1: pipeline persistido deve preservar disposição")
def test_pipeline_state_roundtrip_preserves_disposition() -> None:
    state = PipelineState(
        source_pdf=Path("synthetic.pdf"),
        normalized=NormalizedIncidentModel(disposition="none"),
    )
    restored = PipelineState.model_validate_json(state.model_dump_json())

    assert restored.normalized is not None
    assert restored.normalized.disposition == "none"
    assert restored.normalized.no_occurrence is True


@pytest.mark.xfail(strict=True, reason="F2.A1: disposição fora do contrato deve ser rejeitada")
def test_normalized_rejects_invalid_disposition() -> None:
    with pytest.raises(ValidationError):
        NormalizedIncidentModel(disposition="empty")  # type: ignore[arg-type]


@pytest.mark.xfail(strict=True, reason="F2.A1: payload legado deve migrar para schema 1.1")
def test_legacy_payload_upgrades_schema_version() -> None:
    model = NormalizedIncidentModel.model_validate(
        {"schema_version": "1.0", "occurrences": []}
    )

    assert model.schema_version == "1.1"


@pytest.mark.xfail(strict=True, reason="F2.A1: flag legada não governa disposição explícita")
def test_legacy_flag_cannot_override_explicit_none() -> None:
    model = NormalizedIncidentModel.model_validate(
        {"disposition": "none", "no_occurrence": False, "occurrences": []}
    )

    assert model.disposition == "none"
    assert model.no_occurrence is True


@pytest.mark.parametrize(
    ("disposition", "occurrences"),
    [
        ("none", [NormalizedOccurrence(description="incompatível")]),
        ("present", []),
        ("unknown", [NormalizedOccurrence(description="incompatível")]),
    ],
)
@pytest.mark.xfail(strict=True, reason="F2.A1: disposição e linhas devem ser coerentes")
def test_normalized_rejects_inconsistent_disposition(
    disposition: str, occurrences: list[NormalizedOccurrence]
) -> None:
    with pytest.raises(ValidationError):
        NormalizedIncidentModel(
            disposition=disposition,  # type: ignore[arg-type]
            occurrences=occurrences,
        )
