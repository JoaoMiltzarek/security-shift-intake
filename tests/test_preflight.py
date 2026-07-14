"""Hermetic tests for scripts/preflight.py — the stdlib env probe.

No git/venv/tesseract required: `scan_dbs` runs against a `tmp_path` tree and `evaluate`
is a pure function fed a hand-built report. Covers the plan's severity contract:
DB outside private → warn; DB tracked outside private → blocker; no tesseract → warn.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scripts.preflight import classify_db, evaluate, scan_dbs


def _clean_report(**over: Any) -> dict[str, Any]:
    """A report where everything is healthy; override single fields per test."""
    report: dict[str, Any] = {
        "repo_root": "/repo",
        "branch": "SSI-1002-hardening",
        "branch_ok": True,
        "expected_branch": None,
        "dirty_tree": {"clean": True, "untracked": [], "modified": [], "dangerous": []},
        "tools": {"uv": "/uv", "python": "/py", "make": "/make"},
        "venv_ok": True,
        "test_baseline": None,
        "dbs": [],
        "symlink_support": True,
        "tesseract": {"present": True, "langs": ["eng"]},
        "browser": {"chromium_present": True, "path": "/x"},
        "precommit_hook_active": True,
    }
    report.update(over)
    return report


def test_classify_db_paths() -> None:
    assert classify_db(Path("private/app.db"), tracked=False) == "expected_private_db"
    assert classify_db(Path("private/other.db"), tracked=False) == "private_db"
    assert classify_db(Path("data/x.db"), tracked=False) == "data_db"
    assert classify_db(Path("foo/y.sqlite"), tracked=False) == "db_outside_private"
    assert classify_db(Path("foo/y.sqlite"), tracked=True) == "tracked_outside_private"


def test_clean_report_is_severity_zero() -> None:
    severity, actions = evaluate(_clean_report())
    assert severity == 0
    assert actions == []


def test_db_outside_private_warns(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x.db").write_bytes(b"SQLite format 3\x00")
    dbs = scan_dbs(tmp_path, tracked=set())
    assert len(dbs) == 1
    assert dbs[0]["classification"] == "data_db"
    assert dbs[0]["outside_private"] is True
    assert len(dbs[0]["sha256"]) == 64
    severity, actions = evaluate(_clean_report(dbs=dbs))
    assert severity >= 1
    assert any("quarantine" in a for a in actions)


def test_db_tracked_outside_private_blocks(tmp_path: Path) -> None:
    (tmp_path / "x.db").write_bytes(b"x")
    dbs = scan_dbs(tmp_path, tracked={"x.db"})
    assert dbs[0]["classification"] == "tracked_outside_private"
    severity, _ = evaluate(_clean_report(dbs=dbs))
    assert severity == 2


def test_expected_private_db_takes_no_action(tmp_path: Path) -> None:
    (tmp_path / "private").mkdir()
    (tmp_path / "private" / "app.db").write_bytes(b"x")
    dbs = scan_dbs(tmp_path, tracked=set())
    assert dbs[0]["classification"] == "expected_private_db"
    assert dbs[0]["outside_private"] is False
    severity, _ = evaluate(_clean_report(dbs=dbs))
    assert severity == 0


def test_missing_tesseract_warns() -> None:
    severity, actions = evaluate(_clean_report(tesseract={"present": False, "langs": []}))
    assert severity == 1
    assert any("tesseract" in a for a in actions)


def test_missing_make_blocks() -> None:
    severity, _ = evaluate(_clean_report(tools={"uv": "/uv", "python": "/py", "make": None}))
    assert severity == 2


@pytest.mark.xfail(strict=True, reason="o preflight ainda ignora uv ausente")
def test_missing_uv_blocks() -> None:
    severity, actions = evaluate(
        _clean_report(tools={"uv": None, "python": "/py", "make": "/make"})
    )

    assert severity == 2
    assert any("uv" in action for action in actions)


@pytest.mark.xfail(strict=True, reason="o preflight ainda ignora a venv inválida")
def test_invalid_venv_blocks() -> None:
    severity, actions = evaluate(_clean_report(venv_ok=False))

    assert severity == 2
    assert any("3.11.15" in action for action in actions)


@pytest.mark.xfail(strict=True, reason="o preflight ainda aceita OCR sem português")
def test_missing_portuguese_tesseract_language_warns() -> None:
    severity, actions = evaluate(
        _clean_report(tesseract={"present": True, "langs": ["eng"]})
    )

    assert severity == 1
    assert any("por" in action for action in actions)
