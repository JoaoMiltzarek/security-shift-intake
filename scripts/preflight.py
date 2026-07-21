#!/usr/bin/env python3
"""Preflight environment probe for the SSI-1002 stabilization protocol (stdlib only).

Runs under a plain ``python3`` — **no** ``uv``, **no** third-party imports — because its
job is precisely to detect a broken/absent venv or a missing ``uv``. A tool must never
validate its own precondition, so this one depends on nothing the environment might lack.

It **detects and reports**; it never mutates the tree. For a SQLite DB found outside
``private/`` it computes a hash and *recommends* quarantine/approval — it never moves or
deletes anything.

    python3 scripts/preflight.py [--json] [--with-test-baseline]

Exit code mirrors severity: ``0`` clean, ``1`` warn, ``2`` blocker.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SEVERITY_CLEAN = 0
SEVERITY_WARN = 1
SEVERITY_BLOCKER = 2

# SQLite family — same rule the privacy guards use, duplicated here on purpose so
# preflight stays import-free (it must run when the venv/package tree is broken).
# Whole SQLite family: base .db/.db3/.s3db/.sqlite/.sqlite2/.sqlite3, each with an
# OPTIONAL -wal/-shm/-journal sidecar (SQLite names them <dbfile>-wal, so app.sqlite3-wal).
# Keep in sync with check_real_data.py's `_DB_EXT` (this stdlib copy stays self-contained).
_DB_RE = re.compile(r"\.(db3?|s3db|sqlite[23]?)(-(wal|shm|journal))?$", re.IGNORECASE)
_BINARY_RE = re.compile(r"\.(pdf|jpe?g|png|webp|tiff?|bmp|gif|xlsx?|docx?|pptx?)$", re.IGNORECASE)

# Directories that never hold committable source; skipped by the tree walk.
_SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "node_modules",
}

# Optional guard: only enforce "wrong branch" when the operator opts in, so preflight
# never blocks itself on a legitimately-named feature branch.
_EXPECTED_BRANCH_ENV = "PREFLIGHT_EXPECTED_BRANCH"


def _run_git(root: Path, *args: str) -> str | None:
    """Run a git command in *root*; return stripped stdout or None if git/repo absent."""
    if not shutil.which("git"):
        return None
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.rstrip()


def repo_root(start: Path) -> Path | None:
    top = _run_git(start, "rev-parse", "--show-toplevel")
    return Path(top) if top else None


def git_branch(root: Path) -> str | None:
    return _run_git(root, "rev-parse", "--abbrev-ref", "HEAD")


def git_tracked(root: Path) -> set[str]:
    out = _run_git(root, "ls-files")
    return {line.strip() for line in out.splitlines() if line.strip()} if out else set()


def git_dirty(root: Path) -> dict[str, Any]:
    """Parse ``git status --porcelain`` into untracked/modified/dangerous buckets."""
    out = _run_git(root, "status", "--porcelain")
    untracked: list[str] = []
    modified: list[str] = []
    dangerous: list[str] = []
    for line in (out or "").splitlines():
        if not line.strip():
            continue
        path = line[3:].strip()
        (untracked if line.startswith("??") else modified).append(path)
        if _DB_RE.search(path) or _BINARY_RE.search(path):
            dangerous.append(path)
    return {
        "clean": not (untracked or modified),
        "untracked": untracked,
        "modified": modified,
        "dangerous": dangerous,
    }


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def classify_db(rel_path: Path, tracked: bool) -> str:
    """Classify a discovered DB. `private/app.db` is expected; tracked-outside is a blocker."""
    parts = rel_path.parts
    if parts and parts[0] == "private":
        return "expected_private_db" if rel_path.as_posix() == "private/app.db" else "private_db"
    if tracked:
        return "tracked_outside_private"
    if "data" in parts:
        return "data_db"
    return "db_outside_private"


def _iter_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for p in root.rglob("*"):
        if p.is_dir() or any(part in _SKIP_DIRS for part in p.parts):
            continue
        files.append(p)
    return files


def scan_dbs(root: Path, tracked: set[str]) -> list[dict[str, Any]]:
    """Find every SQLite DB under *root*, hash it, and classify it (never mutates)."""
    found: list[dict[str, Any]] = []
    for p in _iter_files(root):
        if not _DB_RE.search(p.name):
            continue
        rel = p.relative_to(root)
        classification = classify_db(rel, rel.as_posix() in tracked)
        try:
            size = p.stat().st_size
            digest = sha256_file(p)
        except OSError:
            size, digest = -1, ""
        found.append(
            {
                "path": rel.as_posix(),
                "outside_private": rel.parts[:1] != ("private",),
                "tracked": rel.as_posix() in tracked,
                "sha256": digest,
                "size_bytes": size,
                "classification": classification,
            }
        )
    return found


def probe_tools() -> dict[str, Any]:
    """Locate uv/python/make via shutil.which — NOT via uv (uv may be what's missing)."""
    return {
        "uv": shutil.which("uv"),
        "python": shutil.which("python3") or shutil.which("python") or sys.executable,
        "make": shutil.which("make"),
    }


def probe_tesseract() -> dict[str, Any]:
    path = shutil.which("tesseract")
    if not path:
        return {"present": False, "langs": []}
    try:
        out = subprocess.run(
            ["tesseract", "--list-langs"], capture_output=True, text=True, timeout=30
        )
        langs = [ln.strip() for ln in out.stdout.splitlines()[1:] if ln.strip()]
    except (OSError, subprocess.SubprocessError):
        langs = []
    return {"present": True, "langs": langs, "path": path}


def probe_browser() -> dict[str, Any]:
    """Detect a Chromium usable by the browser-smoke gate (system or Playwright cache)."""
    for exe in ("chromium", "chromium-browser", "google-chrome", "chrome"):
        found = shutil.which(exe)
        if found:
            return {"chromium_present": True, "path": found}
    candidates = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH"), "/opt/pw-browsers"]
    home = os.environ.get("HOME") or os.environ.get("USERPROFILE")
    if home:
        candidates.append(str(Path(home) / ".cache" / "ms-playwright"))
    for cand in candidates:
        if cand and Path(cand).is_dir() and any(Path(cand).glob("chromium-*")):
            return {"chromium_present": True, "path": cand}
    return {"chromium_present": False, "path": None}


def symlink_support() -> bool:
    try:
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "t"
            target.write_text("x", encoding="utf-8")
            (Path(d) / "l").symlink_to(target)
        return True
    except (OSError, NotImplementedError):
        return False


def precommit_hook_active(root: Path) -> bool:
    hook = root / ".git" / "hooks" / "pre-commit"
    try:
        return hook.is_file() and hook.stat().st_size > 0
    except OSError:
        return False


def probe_venv(root: Path) -> dict[str, Any]:
    """Verify that the repository venv runs the exact declared Python patch."""
    try:
        expected = (root / ".python-version").read_text(encoding="utf-8").strip()
    except OSError:
        expected = None
    relative = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    executable = root / ".venv" / relative
    if not executable.is_file():
        return {
            "ok": False,
            "executable": str(executable),
            "version": None,
            "expected_version": expected,
        }
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        result = subprocess.run(
            [str(executable), "-c", "import platform; print(platform.python_version())"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        version = None
    else:
        version = result.stdout.strip() if result.returncode == 0 else None
    return {
        "ok": bool(expected and version == expected),
        "executable": str(executable),
        "version": version,
        "expected_version": expected,
    }


def collect_test_baseline(root: Path) -> int | None:
    """Best-effort test count without syncing or writing Python/pytest caches."""
    if not shutil.which("uv"):
        return None
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        out = subprocess.run(
            [
                "uv",
                "run",
                "--locked",
                "--no-sync",
                "pytest",
                "--collect-only",
                "-q",
                "-p",
                "no:cacheprovider",
            ],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"(\d+)\s+tests?\s+collected", out.stdout)
    return int(m.group(1)) if m else None


def build_report(start: Path, with_test_baseline: bool = False) -> dict[str, Any]:
    root = repo_root(start)
    base = root or start
    tracked = git_tracked(base)
    branch = git_branch(base)
    expected = os.environ.get(_EXPECTED_BRANCH_ENV)
    venv = probe_venv(base)
    return {
        "repo_root": str(root) if root else None,
        "branch": branch,
        "branch_ok": expected is None or branch == expected,
        "expected_branch": expected,
        "dirty_tree": git_dirty(base),
        "tools": probe_tools(),
        "venv_ok": venv["ok"],
        "venv": venv,
        "test_baseline": collect_test_baseline(base) if with_test_baseline else None,
        "dbs": scan_dbs(base, tracked),
        "symlink_support": symlink_support(),
        "tesseract": probe_tesseract(),
        "browser": probe_browser(),
        "precommit_hook_active": precommit_hook_active(base),
    }


def evaluate(report: dict[str, Any]) -> tuple[int, list[str]]:
    """Derive severity (0/1/2) and recommended actions from a report — pure, testable."""
    severity = SEVERITY_CLEAN
    actions: list[str] = []

    def bump(level: int, action: str) -> None:
        nonlocal severity
        severity = max(severity, level)
        actions.append(action)

    if not report.get("repo_root"):
        bump(SEVERITY_BLOCKER, "run preflight inside the git repository")
    tools = report["tools"]
    if not tools.get("uv"):
        bump(SEVERITY_BLOCKER, "install uv to reproduce the locked environment")
    if not tools.get("python"):
        bump(SEVERITY_BLOCKER, "install python3")
    if not tools.get("make"):
        bump(SEVERITY_BLOCKER, "install make (Linux/WSL); Windows native is a documented fallback")
    if report.get("venv_ok") is not True:
        venv = report.get("venv") or {}
        expected_version = venv.get("expected_version") or "declared in .python-version"
        bump(
            SEVERITY_BLOCKER,
            f"recreate .venv with exact Python {expected_version} via `uv sync --locked`",
        )
    if report.get("branch_ok") is False and not report["dirty_tree"]["clean"]:
        bump(SEVERITY_BLOCKER, "wrong branch with a dirty tree — switch branch or commit/stash")

    for db in report["dbs"]:
        c = db["classification"]
        tag = f"{db['path']} (sha256 {db['sha256'][:12]}, {db['size_bytes']} bytes)"
        if c == "tracked_outside_private":
            bump(SEVERITY_BLOCKER, f"DB tracked outside private/: {tag} — untrack it")
        elif c in ("data_db", "db_outside_private"):
            bump(SEVERITY_WARN, f"DB outside private/: {tag} — recommend private/quarantine/")

    if not report["tesseract"]["present"]:
        bump(SEVERITY_WARN, "install tesseract-ocr (+por +eng); OCR path else skips")
    elif "por" not in report["tesseract"].get("langs", []):
        bump(SEVERITY_WARN, "install the Tesseract 'por' language pack for release evaluation")
    if not report["browser"]["chromium_present"]:
        bump(SEVERITY_WARN, "install Playwright Chromium for browser-smoke (CI is authoritative)")
    if not report["precommit_hook_active"]:
        bump(SEVERITY_WARN, "activate the pre-commit hook (scripts/check_real_data.py)")
    if report["dirty_tree"]["dangerous"]:
        danger = ", ".join(report["dirty_tree"]["dangerous"])
        bump(SEVERITY_WARN, f"dangerous dirty files: {danger}")

    return severity, actions


def _print_human(report: dict[str, Any]) -> None:
    sev = report["severity"]
    label = {0: "CLEAN", 1: "WARN", 2: "BLOCKER"}[sev]
    print(f"preflight: severity {sev} ({label})")
    print(f"  repo: {report['repo_root']}  branch: {report['branch']}")
    print(f"  venv_ok: {report['venv_ok']}")
    t = report["tools"]
    print(f"  tools: uv={bool(t['uv'])} make={bool(t['make'])} python={bool(t['python'])}")
    print(
        f"  tesseract: {report['tesseract']['present']}  "
        f"chromium: {report['browser']['chromium_present']}  symlinks: {report['symlink_support']}"
    )
    print(f"  dbs: {len(report['dbs'])}  pre-commit hook: {report['precommit_hook_active']}")
    if report["recommended_actions"]:
        print("  recommended actions:")
        for a in report["recommended_actions"]:
            print(f"    - {a}")


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    with_baseline = "--with-test-baseline" in argv
    report = build_report(Path.cwd(), with_test_baseline=with_baseline)
    severity, actions = evaluate(report)
    report["recommended_actions"] = actions
    report["severity"] = severity
    if as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report)
    return severity


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
