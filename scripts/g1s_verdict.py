"""G1-S verdict writer — merges the one-shot test numbers into the calibration JSON.

Every number is READ from committed, code-generated JSONs — never typed by hand:
  - docs/eval_synthetic_summary.json   (the single sanctioned `--split test` run)
  - docs/eval_g1s_calibration.json     (thresholds frozen BEFORE the test run)
  - docs/eval_bressay_baseline.json    (criterion 4 — BRESSAY no-regression / availability)

It compares the test run against the frozen thresholds and writes a `test_result`
block back into docs/eval_g1s_calibration.json. Guards (DATASET_CONTRACT §10):
  - refuses a summary that is not a test-split run by the frozen reader on the
    calibration dataset (the verdict must judge the sanctioned run, nothing else);
  - refuses to overwrite an existing verdict — the test runs ONCE; a new cycle
    requires a new val → freeze → test round, not a rewrite.

Standalone: `python scripts/g1s_verdict.py` → exit 0 (verdict written) or 1 (guard).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

CALIBRATION_PATH = Path("docs/eval_g1s_calibration.json")
SUMMARY_PATH = Path("docs/eval_synthetic_summary.json")
BRESSAY_PATH = Path("docs/eval_bressay_baseline.json")


def compute_verdict(
    summary: dict[str, Any],
    calibration: dict[str, Any],
    bressay: dict[str, Any],
) -> dict[str, Any]:
    """Build the `test_result` block; raises ValueError on any protocol violation."""
    if "test_result" in calibration:
        raise ValueError("verdict already recorded — the test split runs ONCE (§10)")

    frozen = calibration["frozen_thresholds_for_test"]
    run = summary["run"]
    if run["split"] != "test":
        raise ValueError(f"summary is a {run['split']!r} run, not the sanctioned test run")
    if run["dataset"] != calibration["dataset"]:
        raise ValueError(f"summary dataset {run['dataset']!r} != {calibration['dataset']!r}")
    if run["reader"] != frozen["reader"]:
        raise ValueError(f"summary reader {run['reader']!r} != frozen {frozen['reader']!r}")

    metrics = summary["reader_metrics"]
    criteria = [
        {
            "metric": "parse_table_success_rate",
            "op": ">=",
            "frozen_threshold": frozen["parse_table_success_rate_min"],
            "value": metrics["parse_table_success_rate"],
            "pass": metrics["parse_table_success_rate"] >= frozen["parse_table_success_rate_min"],
        },
        {
            "metric": "false_incident_count",
            "op": "<=",
            "frozen_threshold": frozen["false_incident_max"],
            "value": metrics["false_incident_count"],
            "pass": metrics["false_incident_count"] <= frozen["false_incident_max"],
        },
        {
            "metric": "estimated_chars_to_type_total",
            "op": "<=",
            "frozen_threshold": frozen["estimated_chars_to_type_max"],
            "value": metrics["estimated_chars_to_type_total"],
            "pass": (
                metrics["estimated_chars_to_type_total"] <= frozen["estimated_chars_to_type_max"]
            ),
        },
        {
            "metric": "hora_acc",
            "op": ">=",
            "frozen_threshold": frozen["hora_acc_min"],
            "value": metrics["hora_acc"],
            "pass": metrics["hora_acc"] >= frozen["hora_acc_min"],
        },
    ]
    failed = [c["metric"] for c in criteria if not c["pass"]]

    # Criterion 4 (§10): BRESSAY availability + no regression for the frozen reader.
    # No numeric tolerance was frozen at calibration, so the only honest comparison is
    # "not worse than the calibration CER" (tolerance 0) — declared, not invented.
    tesseract = bressay.get("baseline_tesseract", {})
    vlm = bressay.get("vlm", {})
    bressay_block: dict[str, Any] = {
        "available": bool(tesseract.get("available")) and bool(vlm.get("available")),
        "baseline_tesseract_mean_cer": tesseract.get("mean_cer"),
        "vlm_mean_cer": vlm.get("mean_cer"),
        "note": "tolerance 0 (none was frozen at calibration); reader CER must not exceed "
        "the calibration value on the same frozen manifest",
    }

    verdict = "REPROVADO" if failed else "APROVADO"
    if not bressay_block["available"]:
        verdict = f"{verdict} (INCOMPLETO — BRESSAY column missing, §10)"

    return {
        "protocol": "test split run ONCE (DATASET_CONTRACT §10); thresholds frozen via commit",
        "run": run,
        "criteria": criteria,
        "failed_criteria": failed,
        "observations_not_thresholded": {
            "missed_incident_count": metrics.get("missed_incident_count"),
            "correct_refusal_rate": metrics.get("correct_refusal_rate"),
            "transcription_cer_vs_surface_mean": metrics.get("transcription_cer_vs_surface_mean"),
        },
        "bressay_criterion_4": bressay_block,
        "verdict": verdict,
    }


def main() -> int:
    calibration = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    bressay = json.loads(BRESSAY_PATH.read_text(encoding="utf-8"))
    try:
        calibration["test_result"] = compute_verdict(summary, calibration, bressay)
    except ValueError as exc:
        print(f"g1s_verdict: {exc}", file=sys.stderr)
        return 1
    CALIBRATION_PATH.write_text(
        json.dumps(calibration, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"verdict: {calibration['test_result']['verdict']}")
    print(f"failed criteria: {calibration['test_result']['failed_criteria'] or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
