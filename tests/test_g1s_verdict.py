"""Tests for the G1-S verdict writer (scripts/g1s_verdict.py).

Named invariants:
  - a test run below a frozen minimum ⇒ REPROVADO, with the failing criterion listed;
  - a test run meeting every frozen threshold ⇒ APROVADO;
  - a non-test split is refused (the verdict judges only the sanctioned run);
  - an existing verdict is never overwritten (the test runs ONCE — §10);
  - a missing BRESSAY column marks the verdict INCOMPLETO instead of inventing a pass.
"""

from __future__ import annotations

from typing import Any

import pytest

from scripts.g1s_verdict import compute_verdict


def _calibration() -> dict[str, Any]:
    return {
        "dataset": "bench-balanced",
        "frozen_thresholds_for_test": {
            "reader": "local_ocr",
            "parse_table_success_rate_min": 0.30,
            "false_incident_max": 6,
            "estimated_chars_to_type_max": 4000,
            "hora_acc_min": 0.0,
        },
    }


def _summary(parse_rate: float = 0.5, split: str = "test") -> dict[str, Any]:
    return {
        "run": {"split": split, "dataset": "bench-balanced", "reader": "local_ocr"},
        "reader_metrics": {
            "parse_table_success_rate": parse_rate,
            "false_incident_count": 1,
            "estimated_chars_to_type_total": 2000,
            "hora_acc": 0.0,
            "missed_incident_count": 0,
            "correct_refusal_rate": 1.0,
            "transcription_cer_vs_surface_mean": 1.0,
        },
    }


def _bressay(vlm_available: bool = True) -> dict[str, Any]:
    vlm: dict[str, Any] = {"available": vlm_available}
    if vlm_available:
        vlm["mean_cer"] = 0.9
    return {
        "baseline_tesseract": {"available": True, "mean_cer": 1.0},
        "vlm": vlm,
    }


def test_below_frozen_minimum_is_reprovado() -> None:
    result = compute_verdict(_summary(parse_rate=0.1111), _calibration(), _bressay())
    assert result["verdict"] == "REPROVADO"
    assert result["failed_criteria"] == ["parse_table_success_rate"]


def test_all_thresholds_met_is_aprovado() -> None:
    result = compute_verdict(_summary(parse_rate=0.5), _calibration(), _bressay())
    assert result["verdict"] == "APROVADO"
    assert result["failed_criteria"] == []


def test_val_split_refused() -> None:
    with pytest.raises(ValueError, match="not the sanctioned test run"):
        compute_verdict(_summary(split="val"), _calibration(), _bressay())


def test_existing_verdict_never_overwritten() -> None:
    calibration = _calibration()
    calibration["test_result"] = {"verdict": "REPROVADO"}
    with pytest.raises(ValueError, match="ONCE"):
        compute_verdict(_summary(), calibration, _bressay())


def test_missing_bressay_column_marks_incompleto() -> None:
    result = compute_verdict(_summary(parse_rate=0.5), _calibration(), _bressay(False))
    assert "INCOMPLETO" in result["verdict"]


def test_numbers_are_copied_not_typed() -> None:
    # The criteria values must be the exact values from the summary JSON.
    result = compute_verdict(_summary(parse_rate=0.1111), _calibration(), _bressay())
    by_metric = {c["metric"]: c for c in result["criteria"]}
    assert by_metric["parse_table_success_rate"]["value"] == 0.1111
    assert by_metric["estimated_chars_to_type_total"]["value"] == 2000
