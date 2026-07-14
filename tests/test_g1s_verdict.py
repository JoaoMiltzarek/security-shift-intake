"""Tests for the G1-S verdict writer (scripts/g1s_verdict.py).

Named invariants:
  - a test run below a frozen minimum ⇒ REPROVADO, with the failing criterion listed;
  - a test run meeting every frozen threshold ⇒ APROVADO;
  - a non-test split is refused (the verdict judges only the sanctioned run);
  - an existing verdict is never overwritten (the test runs ONCE — §10);
  - BRESSAY is a non-thresholded observation and never changes the verdict.
"""

from __future__ import annotations

import json
from pathlib import Path
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
            "safe_illegible_refusal_rate": 1.0,
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


@pytest.mark.xfail(
    strict=True,
    reason="BRESSAY ausente ainda altera o veredito sintético",
)
def test_missing_bressay_is_a_nonblocking_observation() -> None:
    result = compute_verdict(_summary(parse_rate=0.5), _calibration(), _bressay(False))
    assert result["verdict"] == "APROVADO"
    observation = result["observations_not_thresholded"]["bressay"]
    assert observation["available"] is False
    assert observation["thresholded"] is False
    assert observation["affects_verdict"] is False


@pytest.mark.xfail(
    strict=True,
    reason="BRESSAY ainda é rotulado como critério sem limiar congelado",
)
def test_bressay_cer_never_changes_or_enters_the_thresholded_verdict() -> None:
    bressay = _bressay()
    bressay["vlm"]["mean_cer"] = 999.0

    result = compute_verdict(_summary(parse_rate=0.5), _calibration(), bressay)

    assert result["verdict"] == "APROVADO"
    assert all("bressay" not in criterion["metric"].lower() for criterion in result["criteria"])
    assert all("bressay" not in metric.lower() for metric in result["failed_criteria"])
    assert "bressay_criterion_4" not in result
    assert result["observations_not_thresholded"]["bressay"]["thresholded"] is False


@pytest.mark.xfail(
    strict=True,
    reason="o artefato histórico ainda afirma um critério BRESSAY inexistente",
)
def test_historical_artifact_labels_bressay_as_nonthresholded() -> None:
    artifact = json.loads(Path("docs/eval_g1s_calibration.json").read_text(encoding="utf-8"))

    assert artifact["test_result"]["verdict"] == "REPROVADO"
    assert artifact["test_result"]["failed_criteria"] == ["parse_table_success_rate"]
    assert "bressay_criterion_4" not in artifact["test_result"]
    observation = artifact["test_result"]["observations_not_thresholded"]["bressay"]
    assert observation["thresholded"] is False
    assert observation["affects_verdict"] is False


def test_numbers_are_copied_not_typed() -> None:
    # The criteria values must be the exact values from the summary JSON.
    result = compute_verdict(_summary(parse_rate=0.1111), _calibration(), _bressay())
    by_metric = {c["metric"]: c for c in result["criteria"]}
    assert by_metric["parse_table_success_rate"]["value"] == 0.1111
    assert by_metric["estimated_chars_to_type_total"]["value"] == 2000
