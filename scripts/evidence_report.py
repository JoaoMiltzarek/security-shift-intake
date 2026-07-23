#!/usr/bin/env python3
"""Assemble the SSI-1002 evidence report from artifacts already produced elsewhere.

This is a **collector**, not an orchestrator: it reads outputs that the verification flow
already generated (preflight JSON, pytest log, privacy-check log, browser-smoke log,
the cockpit screenshot) and stitches them into a private local report. It never
re-runs the pipeline or the CI.

Anti-self-reference: the committed file references the PARENT commit SHA + tree hash it
was generated against — never its own HEAD, which a committed self-SHA would invalidate.
The authoritative report (stamped with the final commit SHA) is produced post-commit as a
CI artifact via ``--authoritative-sha`` and uploaded, not committed.

    uv run --locked python -m scripts.evidence_report [--out PATH] [--preflight preflight.json]
        [--pytest-log pytest.log] [--privacy-log privacy.log] [--smoke-log smoke.log]
        [--authoritative-sha <sha>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from src.paths import PRIVATE_ROOT

DEFAULT_OUT = PRIVATE_ROOT / "audit" / "SSI-1002_EVIDENCE.md"
REPO_ROOT = Path(__file__).resolve().parents[1]
SCREENSHOT = REPO_ROOT / "private" / "audit" / "browser_smoke.png"
_MISSING = "_not collected — see the command in this section; CI produces the authoritative copy._"


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _read(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _section(title: str, body: str | None, hint: str, *, fenced: bool = False) -> str:
    if not body:
        return f"## {title}\n\n{_MISSING}\n\n> Reproduce: `{hint}`\n"
    rendered = f"```\n{body}\n```" if fenced else body
    return f"## {title}\n\n{rendered}\n"


def _privacy_summary(log: str | None) -> str | None:
    """Reduce privacy evidence to a fixed pass token; never copy scanner output."""
    if log is None:
        return None
    if "privacy-check OK" not in log or "FAILED" in log or "BLOCKED" in log:
        raise ValueError("privacy evidence is not a successful privacy-check result")
    return "privacy-check OK — successful gate (raw detector output intentionally omitted)"


def _preflight_summary(raw: str | None) -> str | None:
    """Whitelist release-relevant booleans; omit paths, DB hashes and local identities."""
    if raw is None:
        return None
    try:
        parsed: object = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("preflight evidence is not valid JSON") from exc
    if type(parsed) is not dict:
        raise ValueError("preflight evidence is not a JSON object")
    payload = cast(dict[str, Any], parsed)

    tools = cast(dict[str, Any], payload.get("tools")) if type(payload.get("tools")) is dict else {}
    tesseract = (
        cast(dict[str, Any], payload.get("tesseract"))
        if type(payload.get("tesseract")) is dict
        else {}
    )
    browser = (
        cast(dict[str, Any], payload.get("browser")) if type(payload.get("browser")) is dict else {}
    )
    dirty = (
        cast(dict[str, Any], payload.get("dirty_tree"))
        if type(payload.get("dirty_tree")) is dict
        else {}
    )
    raw_langs = (
        cast(list[Any], tesseract.get("langs")) if type(tesseract.get("langs")) is list else []
    )
    langs = [
        value
        for value in raw_langs
        if type(value) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,32}", value)
    ]
    dbs = cast(list[Any], payload.get("dbs")) if type(payload.get("dbs")) is list else []
    db_counts: dict[str, int] = {}
    for item in dbs:
        if type(item) is not dict or type(item.get("classification")) is not str:
            continue
        classification = item["classification"]
        if re.fullmatch(r"[a-z_]{1,40}", classification):
            db_counts[classification] = db_counts.get(classification, 0) + 1

    safe = {
        "severity": payload.get("severity"),
        "branch_ok": payload.get("branch_ok"),
        "dirty_tree_clean": dirty.get("clean"),
        "venv_ok": payload.get("venv_ok"),
        "tools_present": {name: bool(tools.get(name)) for name in ("uv", "python", "make")},
        "test_baseline": payload.get("test_baseline"),
        "db_classification_counts": db_counts,
        "symlink_support": payload.get("symlink_support"),
        "tesseract": {"present": tesseract.get("present"), "langs": langs},
        "browser_present": browser.get("chromium_present"),
        "precommit_hook_active": payload.get("precommit_hook_active"),
    }
    return json.dumps(safe, indent=2, sort_keys=True)


def _pytest_summary(log: str | None) -> str | None:
    """Keep only the successful count/duration token, never the raw test log."""
    if log is None:
        return None
    if re.search(r"\b(?:failed|errors?)\b", log, re.IGNORECASE):
        raise ValueError("pytest evidence contains a failure token")
    matches: list[str] = re.findall(
        r"(?m)(\d+ passed(?:, \d+ (?:skipped|xfailed|xpassed|deselected))*(?: in \d+(?:\.\d+)?s)?)",
        log,
    )
    if not matches:
        raise ValueError("pytest evidence has no successful summary")
    return matches[-1]


def _smoke_summary(log: str | None) -> str | None:
    """Reduce browser output to a pass token; screenshot identity is carried by its hash."""
    if log is None:
        return None
    if "browser-smoke OK" not in log or "FAILED" in log or "REPORTED" in log:
        raise ValueError("browser-smoke evidence is not a successful result")
    return "browser-smoke OK — successful real-browser gate (raw log intentionally omitted)"


def render_report(
    *,
    branch: str | None,
    parent_sha: str | None,
    tree_hash: str | None,
    authoritative_sha: str | None,
    preflight: str | None,
    pytest_log: str | None,
    privacy_log: str | None,
    smoke_log: str | None,
    screenshot_sha: str | None,
) -> str:
    """Render the evidence markdown from already-collected pieces (pure/testable)."""
    auth = authoritative_sha or "pending — see the post-commit CI artifact"
    safe_preflight = _preflight_summary(preflight)
    safe_pytest_log = _pytest_summary(pytest_log)
    safe_privacy_log = _privacy_summary(privacy_log)
    safe_smoke_log = _smoke_summary(smoke_log)
    screenshot = (
        f"Synthetic cockpit screenshot — sha256 `{screenshot_sha}` (real browser capture)"
        if screenshot_sha
        else None
    )
    parts = [
        "# SSI-1002 — Evidence Report (Evidence Cockpit stabilization)",
        "",
        "> Anti-self-reference: this committed file references the **parent** commit + tree",
        "> it was generated against — never its own HEAD (a committed self-SHA would",
        "> invalidate its own hash). The authoritative report, stamped with the final commit",
        "> SHA, is produced post-commit as a CI artifact (uploaded, not committed).",
        "",
        f"- Branch: `{branch or 'unknown'}`",
        f"- Parent commit: `{parent_sha or 'unknown'}`",
        f"- Tree hash: `{tree_hash or 'unknown'}`",
        f"- Authoritative commit (CI): {auth}",
        "- Generated by: `scripts/evidence_report.py` (collector — does not re-run pipeline/CI)",
        "",
        _section(
            "Preflight",
            safe_preflight,
            "python3 scripts/preflight.py --json > preflight.json",
            fenced=True,
        ),
        _section(
            "Tests (make check)",
            safe_pytest_log,
            "make check 2>&1 | tee pytest.log",
            fenced=True,
        ),
        _section(
            "Privacy check",
            safe_privacy_log,
            "make privacy-check 2>&1 | tee privacy.log",
            fenced=True,
        ),
        _section(
            "Browser-smoke (cockpit UI gate — CI authoritative)",
            safe_smoke_log,
            "uv run --locked python scripts/browser_smoke.py 2>&1 | tee smoke.log",
            fenced=True,
        ),
        _section(
            "Screenshot (real page capture)",
            screenshot,
            "produced by scripts/browser_smoke.py step (8)",
        ),
        "## Invariants",
        "",
        "- Real data only in `private/`; public artifacts carry synthetic examples only.",
        "- Operational export stays blocked while any field is pending.",
        "- A `bbox` is a *probable* region, not proof; `source==human` drops the box.",
        "- No email is sent without explicit human approval.",
        "",
    ]
    return "\n".join(parts)


def collect(args: argparse.Namespace) -> str:
    screenshot_sha = _sha256(SCREENSHOT) if SCREENSHOT.is_file() else None
    return render_report(
        branch=_git("rev-parse", "--abbrev-ref", "HEAD"),
        parent_sha=_git("rev-parse", "HEAD"),
        tree_hash=_git("rev-parse", "HEAD^{tree}"),
        authoritative_sha=args.authoritative_sha,
        preflight=_read(args.preflight),
        pytest_log=_read(args.pytest_log),
        privacy_log=_read(args.privacy_log),
        smoke_log=_read(args.smoke_log),
        screenshot_sha=screenshot_sha,
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Collect the SSI-1002 evidence report.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--preflight", type=Path, default=Path("preflight.json"))
    parser.add_argument("--pytest-log", type=Path, default=None)
    parser.add_argument("--privacy-log", type=Path, default=None)
    parser.add_argument("--smoke-log", type=Path, default=None)
    parser.add_argument("--authoritative-sha", type=str, default=None)
    args = parser.parse_args(argv)

    report = collect(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print(f"evidence report written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
