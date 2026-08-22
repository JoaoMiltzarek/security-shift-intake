"""Hermetic tests for scripts/preflight.py — the stdlib env probe.

No git/venv/tesseract required: `scan_dbs` runs against a `tmp_path` tree and `evaluate`
is a pure function fed a hand-built report. Covers the plan's severity contract:
DB outside private → warn; DB tracked outside private → blocker; no tesseract → warn.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import scripts.preflight as preflight
from scripts.preflight import classify_db, evaluate, scan_dbs


def _clean_report(**over: Any) -> dict[str, Any]:
    """A report where everything is healthy; override single fields per test."""
    report: dict[str, Any] = {
        "repo_root": "/repo",
        "branch": "SSI-1002-hardening",
        "branch_ok": True,
        "expected_branch": None,
        "dirty_tree": {"clean": True, "untracked": [], "modified": [], "dangerous": []},
        "tools": {"git": "/git", "uv": "/uv", "python": "/py", "make": "/make"},
        "runtime": {
            "executable": "/py",
            "version": "3.11.15",
            "implementation": "CPython",
        },
        "venv_ok": True,
        "venv": {
            "ok": True,
            "executable": "/repo/.venv/bin/python",
            "version": "3.11.15",
            "expected_version": "3.11.15",
        },
        "test_baseline": None,
        "dbs": [],
        "symlink_support": True,
        "tesseract": {"present": True, "langs": ["eng", "por"]},
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


def test_missing_uv_blocks() -> None:
    severity, actions = evaluate(
        _clean_report(tools={"uv": None, "python": "/py", "make": "/make"})
    )

    assert severity == 2
    assert any("uv" in action for action in actions)


def test_invalid_venv_blocks() -> None:
    severity, actions = evaluate(_clean_report(venv_ok=False))

    assert severity == 2
    assert any("3.11.15" in action for action in actions)


def test_missing_portuguese_tesseract_language_warns() -> None:
    severity, actions = evaluate(_clean_report(tesseract={"present": True, "langs": ["eng"]}))

    assert severity == 1
    assert any("por" in action for action in actions)


def test_git_output_preserves_leading_porcelain_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = SimpleNamespace(returncode=0, stdout=" M scripts/preflight.py\n")
    monkeypatch.setattr(preflight.shutil, "which", lambda _name: "/git")
    captured: dict[str, Any] = {}

    def run(command: list[str], **_kwargs: Any) -> SimpleNamespace:
        captured["command"] = command
        return result

    monkeypatch.setattr(preflight.subprocess, "run", run)

    output = preflight._run_git(tmp_path, "status", "--porcelain")

    assert output == " M scripts/preflight.py"
    assert captured["command"] == ["/git", "status", "--porcelain"]


def test_untracked_webp_is_classified_as_dangerous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, tuple[str, ...]] = {}

    def run(_root: Path, *args: str) -> str:
        captured["args"] = args
        return "?? leaked-page.webp\0"

    monkeypatch.setattr(preflight, "_run_git", run)

    dirty = preflight.git_dirty(tmp_path)

    assert dirty["untracked"] == ["leaked-page.webp"]
    assert dirty["dangerous"] == ["leaked-page.webp"]
    assert captured["args"] == (
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    )


def test_git_status_preserves_unusual_and_renamed_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = "?? leading space.webp\0R  renamed.txt\0old\npage.png\0"
    monkeypatch.setattr(preflight, "_run_git", lambda *_args: output)

    dirty = preflight.git_dirty(tmp_path)

    assert dirty["untracked"] == ["leading space.webp"]
    assert dirty["modified"] == ["renamed.txt"]
    assert dirty["dangerous"] == ["leading space.webp", "old\npage.png"]


def test_probe_tools_reports_the_active_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "active-python"
    monkeypatch.setattr(preflight.sys, "executable", str(executable))
    monkeypatch.setattr(preflight.shutil, "which", lambda name: f"/{name}")

    tools = preflight.probe_tools()

    assert tools == {
        "git": "/git",
        "uv": "/uv",
        "python": str(executable.resolve()),
        "make": "/make",
    }


def test_precommit_hook_uses_the_active_worktree_git_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook = tmp_path / "common-git-dir" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True)
    hook.write_text("#!/bin/sh\n", encoding="utf-8")
    hook.chmod(0o700)
    monkeypatch.setattr(preflight, "_run_git", lambda *_args: str(hook))

    assert preflight.precommit_hook_active(tmp_path) is True


def test_precommit_hook_must_be_executable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hook = tmp_path / "hooks" / "pre-commit"
    hook.parent.mkdir()
    hook.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(preflight, "_run_git", lambda *_args: str(hook))
    monkeypatch.setattr(preflight.os, "access", lambda *_args: False)

    assert preflight.precommit_hook_active(tmp_path) is False


def test_test_baseline_is_locked_no_sync_and_cache_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    def run(command: list[str], **kwargs: Any) -> SimpleNamespace:
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="812 tests collected\n")

    monkeypatch.setattr(preflight.shutil, "which", lambda _name: "/uv")
    monkeypatch.setattr(preflight.subprocess, "run", run)

    assert preflight.collect_test_baseline(tmp_path) == 812
    assert captured["command"] == [
        "uv",
        "run",
        "--locked",
        "--no-sync",
        "pytest",
        "--collect-only",
        "-q",
        "-p",
        "no:cacheprovider",
    ]
    assert captured["env"]["PYTHONDONTWRITEBYTECODE"] == "1"


def test_test_baseline_supports_pytest_grouped_collection_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = SimpleNamespace(
        returncode=0,
        stdout="tests/test_api.py: 12\ntests/test_preflight.py: 16\n",
    )
    monkeypatch.setattr(preflight.shutil, "which", lambda _name: "/uv")
    monkeypatch.setattr(preflight.subprocess, "run", lambda *_args, **_kwargs: result)

    assert preflight.collect_test_baseline(tmp_path) == 28


def test_test_baseline_rejects_failed_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = SimpleNamespace(returncode=2, stdout="tests/test_api.py: 12\n")
    monkeypatch.setattr(preflight.shutil, "which", lambda _name: "/uv")
    monkeypatch.setattr(preflight.subprocess, "run", lambda *_args, **_kwargs: result)

    assert preflight.collect_test_baseline(tmp_path) is None
