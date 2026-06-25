"""Tests for the real-sheet audit (evals/eval_extraction_real.py) pure helpers.

No Tesseract / no pipeline run here — only the deterministic classification, status,
and aggregation logic. One scenario per test for pinpoint failures.
"""

from __future__ import annotations

from typing import Any

from evals.eval_extraction_real import (
    aggregate,
    classify_errors,
    curated_header,
    field_status,
    has_occurrence,
)
from src.schema.state import ExtractedField


def _ef(name: str, value: Any, must_review: bool = False) -> ExtractedField:
    conf = 0.0 if value is None else 0.65
    return ExtractedField(name=name, value=value, confidence=conf, must_review=must_review)


def _sa_sheet() -> dict[str, Any]:
    return {
        "document_id": "d-sa",
        "review_status": "verified_by_user",
        "cabecalho": {"data": "01/01", "vigilantes": ["A", "B"], "unidade": "Posto"},
        "sem_alteracao": True,
        "riscado": False,
        "ocorrencias": [],
    }


def _occ_sheet() -> dict[str, Any]:
    return {
        "document_id": "d-occ",
        "review_status": "verified_by_user",
        "cabecalho": {"data": "01/01", "vigilantes": ["A"], "unidade": "Posto"},
        "sem_alteracao": False,
        "riscado": False,
        "ocorrencias": [
            {"item": "Acesso", "descricao": "Prestador acessa para manutenção.", "resolvido": "sim"}
        ],
    }


# --- field_status -----------------------------------------------------------


def test_status_missing_for_none() -> None:
    assert field_status(None, False) == "missing"


def test_status_must_review_for_flagged_value() -> None:
    assert field_status("x", True) == "must_review"


def test_status_accepted_for_clean_value() -> None:
    assert field_status("x", False) == "accepted"


# --- has_occurrence ---------------------------------------------------------


def test_sem_alteracao_has_no_occurrence() -> None:
    assert has_occurrence(_sa_sheet()) is False


def test_riscado_has_no_occurrence() -> None:
    sheet = _occ_sheet()
    sheet["riscado"] = True
    assert has_occurrence(sheet) is False


def test_real_occurrence_detected() -> None:
    assert has_occurrence(_occ_sheet()) is True


def test_curated_header_joins_vigilantes() -> None:
    assert curated_header(_occ_sheet(), "vigilantes") == "A"
    assert curated_header(_sa_sheet(), "vigilantes") == "A, B"


# --- classify_errors --------------------------------------------------------


def test_false_incident_is_blocker() -> None:
    # S/A sheet, but the system produced a description -> FALSE_INCIDENT (BLOCKER).
    extracted = [_ef("incident_description", "algum texto")]
    errs = classify_errors(_sa_sheet(), extracted)
    fi = [e for e in errs if e["type"] == "FALSE_INCIDENT"]
    assert fi and fi[0]["severity"] == "BLOCKER"


def test_missed_incident_is_blocker() -> None:
    # Occurrence sheet, system captured nothing -> MISSED_INCIDENT (BLOCKER).
    extracted = [_ef("incident_description", None)]
    errs = classify_errors(_occ_sheet(), extracted)
    mi = [e for e in errs if e["type"] == "MISSED_INCIDENT"]
    assert mi and mi[0]["severity"] == "BLOCKER"


def test_field_not_found_for_missing_header() -> None:
    extracted = [_ef("guard_name", None), _ef("incident_description", "x")]
    errs = classify_errors(_sa_sheet(), extracted)
    assert any(e["type"] == "FIELD_NOT_FOUND" and e["field"] == "guard_name" for e in errs)


def test_table_row_split_for_multirow() -> None:
    sheet = _occ_sheet()
    sheet["ocorrencias"].append(
        {"item": "Ronda", "descricao": "Segunda linha.", "resolvido": "sim"}
    )
    errs = classify_errors(sheet, [_ef("incident_description", None)])
    assert any(e["type"] == "TABLE_ROW_SPLIT_ERROR" and e["severity"] == "HIGH" for e in errs)


def test_needs_human_review_tallied() -> None:
    extracted = [_ef("incident_description", "x", must_review=True)]
    errs = classify_errors(_sa_sheet(), extracted)
    assert any(e["type"] == "NEEDS_HUMAN_REVIEW" and e["severity"] == "LOW" for e in errs)


# --- aggregate --------------------------------------------------------------


def test_aggregate_counts() -> None:
    per_sheet = [
        {
            "ran": True,
            "status": "ok",
            "review_status": "verified_by_user",
            "errors": [
                {"type": "MISSED_INCIDENT", "severity": "BLOCKER", "field": "incident_description"}
            ],
            "field_statuses": {"a": "missing", "b": "must_review"},
            "n_occurrences_curated": 1,
            "n_occurrences_captured": 0,
            "ocr_confidence": 0.4,
        },
        {
            "ran": False,
            "status": "pending_file",
            "review_status": "draft_by_claude",
            "errors": [],
            "field_statuses": {},
            "n_occurrences_curated": 1,
            "n_occurrences_captured": 0,
            "ocr_confidence": 0.0,
        },
    ]
    agg = aggregate(per_sheet)
    assert agg["n_sheets_total"] == 2
    assert agg["n_sheets_run"] == 1
    assert agg["n_sheets_pending_file"] == 1
    assert agg["errors_by_severity"]["BLOCKER"] == 1
    assert agg["field_status_counts"]["missing"] == 1
    assert agg["n_verified_by_user"] == 1
