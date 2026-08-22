"""The public reader history should stay concise, neutral, and non-executable."""

from __future__ import annotations

from pathlib import Path


def _decision() -> str:
    return " ".join(Path("docs/READER_DECISION.md").read_text(encoding="utf-8").split())


def test_reader_decision_states_the_supported_baseline_and_limit() -> None:
    decision = _decision()

    assert "only document reader" in decision
    assert "does not imply reliable cursive-handwriting recognition" in decision
    assert "uncertainty stays visible" in decision
    assert "structural-safety gates" in decision


def test_reader_decision_preserves_conclusions_without_active_adapters() -> None:
    decision = _decision()

    assert "They are not runtime options in v1.1" in decision
    assert "produced more false incidents" in decision
    assert "did not reconstruct usable table rows" in decision
    assert "was never a release gate" in decision
    assert "old measurements are not current release evidence" in decision


def test_reader_history_points_to_the_immutable_git_record() -> None:
    decision = _decision()

    assert "tree/v1.0.0" in decision
    assert "repository's Git history" in decision
    assert "keeps only this concise conclusion" in decision


def test_reader_decision_sets_fail_closed_adoption_rules() -> None:
    decision = _decision()

    assert "authenticated corpus and runtime metadata" in decision
    assert "without winning by returning empty" in decision
    assert "acceptance thresholds must be committed" in decision
    assert "separate versioned change" in decision


def test_reader_history_contains_no_retired_runtime_command() -> None:
    decision = Path("docs/READER_DECISION.md").read_text(encoding="utf-8")

    assert "uv run" not in decision
    assert "make " not in decision
    assert "localhost:" not in decision
