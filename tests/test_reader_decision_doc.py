"""Normative reader policy must match the executable SSI-1010 safety gates."""

from __future__ import annotations

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
