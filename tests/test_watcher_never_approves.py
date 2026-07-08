"""Tests for IntakeWatcher — named invariants (F4).

Named invariants per plan:
- test_watcher_never_approves
- test_idempotency_skips_duplicate_sha256
- test_quarantine_on_pipeline_error
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.intake_watch import IntakeWatcher, WatchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pdf(path: Path, content: bytes = b"%PDF-synthetic") -> Path:
    path.write_bytes(content)
    return path


def _noop_pipeline(pdf: Path) -> dict[str, Any]:
    return {"email_draft": f"draft for {pdf.name}"}


def _failing_pipeline(pdf: Path) -> dict[str, Any]:
    raise RuntimeError("simulated pipeline failure")


def _make_watcher(tmp_path: Path, pipeline_fn=None, stability_secs: float = 0.0) -> IntakeWatcher:
    return IntakeWatcher(
        watch_dir=tmp_path,
        pipeline_fn=pipeline_fn or _noop_pipeline,
        poll_interval=0.0,
        stability_secs=stability_secs,
    )


# ---------------------------------------------------------------------------
# Named invariant: watcher never approves / never sends email
# ---------------------------------------------------------------------------


def test_watcher_never_approves(tmp_path: Path) -> None:
    """Watcher must only write drafts. No 'approved' or 'sent' state ever set."""
    _make_pdf(tmp_path / "report.pdf")
    watcher = _make_watcher(tmp_path)

    watcher.pipeline_fn = lambda p: {"email_draft": "DRAFT ONLY"}
    results = watcher.scan_once()

    assert len(results) == 1
    r = results[0]
    assert r.action == "processed"
    # Draft written — never "sent" or "approved"
    assert r.draft_path is not None
    assert r.draft_path.exists()
    draft_text = r.draft_path.read_text(encoding="utf-8")
    assert draft_text == "DRAFT ONLY"
    # WatchResult carries no approval field
    assert not hasattr(r, "approved")
    assert not hasattr(r, "sent")


# ---------------------------------------------------------------------------
# Named invariant: idempotency — same sha256 → one draft, one log entry
# ---------------------------------------------------------------------------


def test_idempotency_skips_duplicate_sha256(tmp_path: Path) -> None:
    """Same file processed twice must yield exactly one draft and one log entry."""
    _make_pdf(tmp_path / "report.pdf")
    watcher = _make_watcher(tmp_path)

    results1 = watcher.scan_once()
    results2 = watcher.scan_once()

    assert results1[0].action == "processed"
    assert results2[0].action == "skipped_duplicate"

    # Exactly one draft file
    drafts = list((tmp_path / "drafts").glob("*.txt"))
    assert len(drafts) == 1

    # Exactly one log entry
    log_lines = (tmp_path / "processed.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(log_lines) == 1


# ---------------------------------------------------------------------------
# Named invariant: quarantine on pipeline error
# ---------------------------------------------------------------------------


def test_quarantine_on_pipeline_error(tmp_path: Path) -> None:
    """A pipeline exception must move the file to quarantine — not lose it."""
    pdf = _make_pdf(tmp_path / "bad.pdf")
    watcher = _make_watcher(tmp_path, pipeline_fn=_failing_pipeline)

    results = watcher.scan_once()

    assert results[0].action == "quarantined"
    assert results[0].error is not None

    # File moved to quarantine, not left in watch_dir root
    assert not pdf.exists()
    quarantine_file = tmp_path / "quarantine" / "bad.pdf"
    assert quarantine_file.exists()

    # No draft created for a quarantined file
    drafts = list((tmp_path / "drafts").glob("*.txt"))
    assert len(drafts) == 0


# ---------------------------------------------------------------------------
# Additional coverage
# ---------------------------------------------------------------------------


def test_scan_once_empty_dir(tmp_path: Path) -> None:
    watcher = _make_watcher(tmp_path)
    assert watcher.scan_once() == []


def test_draft_content_matches_pipeline_output(tmp_path: Path) -> None:
    _make_pdf(tmp_path / "x.pdf")
    watcher = _make_watcher(tmp_path, pipeline_fn=lambda p: {"email_draft": "Olá mundo"})
    results = watcher.scan_once()
    text = results[0].draft_path.read_text(encoding="utf-8")
    assert text == "Olá mundo"


def test_draft_empty_when_pipeline_returns_none_draft(tmp_path: Path) -> None:
    _make_pdf(tmp_path / "x.pdf")
    watcher = _make_watcher(tmp_path, pipeline_fn=lambda p: {"email_draft": None})
    results = watcher.scan_once()
    assert results[0].draft_path.read_text(encoding="utf-8") == ""


def test_processed_jsonl_appended(tmp_path: Path) -> None:
    _make_pdf(tmp_path / "a.pdf", b"%PDF-A")
    _make_pdf(tmp_path / "b.pdf", b"%PDF-B")
    watcher = _make_watcher(tmp_path)
    watcher.scan_once()
    lines = (tmp_path / "processed.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    entries = [json.loads(ln) for ln in lines]
    assert all(e["action"] == "processed" for e in entries)
    shas = {e["sha256"] for e in entries}
    assert len(shas) == 2  # distinct files → distinct shas


def test_two_different_files_both_processed(tmp_path: Path) -> None:
    _make_pdf(tmp_path / "a.pdf", b"%PDF-A")
    _make_pdf(tmp_path / "b.pdf", b"%PDF-B")
    watcher = _make_watcher(tmp_path)
    results = watcher.scan_once()
    assert len(results) == 2
    assert all(r.action == "processed" for r in results)


def test_watch_dir_created_on_init(tmp_path: Path) -> None:
    watch = tmp_path / "inbox"
    watch.mkdir()
    watcher = IntakeWatcher(watch_dir=watch, pipeline_fn=_noop_pipeline)
    assert (watch / "drafts").is_dir()
    assert (watch / "quarantine").is_dir()


def test_is_processed_returns_false_for_unknown_sha(tmp_path: Path) -> None:
    watcher = _make_watcher(tmp_path)
    assert not watcher.is_processed("deadbeef" * 8)


def test_quarantine_error_recorded_in_result(tmp_path: Path) -> None:
    _make_pdf(tmp_path / "err.pdf")
    watcher = _make_watcher(tmp_path, pipeline_fn=_failing_pipeline)
    r = watcher.scan_once()[0]
    assert "simulated pipeline failure" in r.error


def test_stability_check_skips_changed_file(tmp_path: Path, monkeypatch) -> None:
    """File that changes during stability wait is skipped this cycle."""
    _make_pdf(tmp_path / "changing.pdf", b"%PDF-v1")

    call_count = {"n": 0}

    def unstable_sha(path: Path) -> str:
        call_count["n"] += 1
        return "sha_v1" if call_count["n"] == 1 else "sha_v2"

    import src.intake_watch as _mod
    monkeypatch.setattr(_mod, "_sha256", unstable_sha)
    monkeypatch.setattr(_mod.time, "sleep", lambda s: None)

    watcher = _make_watcher(tmp_path, stability_secs=0.001)
    results = watcher.scan_once()
    assert results[0].action == "skipped_unstable"
