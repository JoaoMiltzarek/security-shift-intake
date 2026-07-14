"""Hermetic tests for scripts/evidence_report.py — the evidence collector.

`render_report` is pure: no git/CI needed. Covers that it references the parent commit +
tree (never re-runs anything), tolerates missing artifacts, and embeds a screenshot hash.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.evidence_report import render_report


def test_render_tolerates_missing_inputs() -> None:
    md = render_report(
        branch="SSI-1002-hardening",
        parent_sha="abc123",
        tree_hash="def456",
        authoritative_sha=None,
        preflight=None,
        pytest_log=None,
        privacy_log=None,
        smoke_log=None,
        screenshot_sha=None,
    )
    assert "Parent commit: `abc123`" in md
    assert "Tree hash: `def456`" in md
    assert "pending" in md  # authoritative commit not yet known
    assert md.count("not collected") >= 4  # every collected section is absent


def test_render_embeds_collected_artifacts() -> None:
    md = render_report(
        branch="b",
        parent_sha="p",
        tree_hash="t",
        authoritative_sha="FINALSHA",
        preflight='{"severity": 1}',
        pytest_log="450 passed, 1 skipped",
        privacy_log="privacy-check OK",
        smoke_log="browser-smoke OK",
        screenshot_sha="a" * 64,
    )
    assert "FINALSHA" in md
    assert "a" * 64 in md
    assert "450 passed, 1 skipped" in md
    assert "browser-smoke OK" in md


def test_render_never_embeds_privacy_log_verbatim() -> None:
    secret = "NOMEREAL-SUPER-SECRETO"
    md = render_report(
        branch="b",
        parent_sha="p",
        tree_hash="t",
        authoritative_sha="sha",
        preflight=None,
        pytest_log=None,
        privacy_log=f"uv run privacy-check\nprivacy-check OK — clean\n{secret}",
        smoke_log=None,
        screenshot_sha=None,
    )

    assert "privacy-check OK" in md
    assert secret not in md
    assert "uv run privacy-check" not in md


def test_render_refuses_failed_privacy_evidence() -> None:
    with pytest.raises(ValueError, match="privacy evidence"):
        render_report(
            branch="b",
            parent_sha="p",
            tree_hash="t",
            authoritative_sha="sha",
            preflight=None,
            pytest_log=None,
            privacy_log="PRIVACY-CHECK FAILED — NOMEREAL-SUPER-SECRETO",
            smoke_log=None,
            screenshot_sha=None,
        )


def test_ci_does_not_collect_or_upload_evidence_after_privacy_failure() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    condition = "if: ${{ success() && steps.privacy.outcome == 'success' }}"

    assert "id: privacy" in workflow
    assert workflow.count(condition) == 2
