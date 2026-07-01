"""Hermetic tests for scripts/evidence_report.py — the evidence collector.

`render_report` is pure: no git/CI needed. Covers that it references the parent commit +
tree (never re-runs anything), tolerates missing artifacts, and embeds a screenshot hash.
"""

from __future__ import annotations

from scripts.evidence_report import render_report


def test_render_tolerates_missing_inputs() -> None:
    md = render_report(
        branch="SSI-1002-hardening", parent_sha="abc123", tree_hash="def456",
        authoritative_sha=None, preflight=None, pytest_log=None,
        privacy_log=None, smoke_log=None, screenshot_sha=None,
    )
    assert "Parent commit: `abc123`" in md
    assert "Tree hash: `def456`" in md
    assert "pending" in md  # authoritative commit not yet known
    assert md.count("not collected") >= 4  # every collected section is absent


def test_render_embeds_collected_artifacts() -> None:
    md = render_report(
        branch="b", parent_sha="p", tree_hash="t", authoritative_sha="FINALSHA",
        preflight='{"severity": 1}', pytest_log="450 passed, 1 skipped",
        privacy_log="privacy-check OK", smoke_log="browser-smoke OK",
        screenshot_sha="a" * 64,
    )
    assert "FINALSHA" in md
    assert "a" * 64 in md
    assert "450 passed, 1 skipped" in md
    assert "browser-smoke OK" in md
