"""Normative reader policy must match the executable SSI-1010 safety gates."""

from __future__ import annotations

import json
from pathlib import Path


def test_reader_decision_separates_candidate_quality_from_release_safety() -> None:
    decision = Path("docs/READER_DECISION.md").read_text(encoding="utf-8")
    required = (
        "false_incident_unreviewed=0",
        "unsafe_clean=0",
        "safe_review_recall=1.0",
        "candidate promotion",
        "baseline fallback",
        "false_incident_count=9",
    )
    assert all(value in decision for value in required)
    assert "false_incident = 0 em ambas as rodadas" not in decision


def test_reader_decision_matches_frozen_calibration() -> None:
    decision = Path("docs/READER_DECISION.md").read_text(encoding="utf-8")
    calibration = json.loads(
        Path("docs/eval_g1s_calibration.json").read_text(encoding="utf-8")
    )

    assert calibration["readers"]["local_ocr"]["false_incident_count"] == 4
    assert calibration["readers"]["local_vlm"]["false_incident_count"] == 9
    assert calibration["decision"]["chosen_reader"] == "local_ocr"
    assert calibration["test_result"]["verdict"] == "REPROVADO"

    forbidden = (
        "O leitor que entra no G1-S é **qwen2.5vl:3b**",
        "chars_to_type ≤ qwen2.5vl:3b",
        "false_incident = 0 em ambas as rodadas",
    )
    assert all(value not in decision for value in forbidden)
