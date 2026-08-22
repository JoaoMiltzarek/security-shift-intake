"""The public reader decision should stay concise and operational."""

from __future__ import annotations

from pathlib import Path


def _decision() -> str:
    return Path("docs/READER_DECISION.md").read_text(encoding="utf-8")


def test_reader_decision_states_the_supported_baseline_and_limit() -> None:
    decision = _decision()

    assert "only document reader" in decision
    assert "does not imply reliable cursive" in decision
    assert "unsafe_approvable=0" in decision
    assert "unsafe_exportable=0" in decision
    assert "safe_review_recall=1.0" in decision


def test_reader_decision_preserves_conclusions_without_active_adapters() -> None:
    decision = _decision()

    assert "They are not runtime options in v1.1" in decision
    assert "produced more false incidents" in decision
    assert "did not reconstruct table rows" in decision
    assert "it was never a release gate" in decision


def test_reader_decision_sets_fail_closed_adoption_rules() -> None:
    decision = _decision()

    assert "authenticated runtime and corpus metadata" in decision
    assert "without winning by returning empty" in decision
    assert "acceptance thresholds are committed" in decision
