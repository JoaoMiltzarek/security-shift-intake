"""Tests for the table-extraction models (src/schema/extraction.py).

One scenario per test. Models are pure data contracts (R1/R2).
"""

from __future__ import annotations

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
