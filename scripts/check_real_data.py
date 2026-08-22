"""Pre-commit guard: reject staged files that look like real (non-synthetic) data.

Called by the pre-commit hook. Exits 0 (clean) or 1 (suspicious patterns found).
Also usable standalone: ``python scripts/check_real_data.py`` scans the Git index.

§9 risk: confidential data leak — real shift reports / names / scans committed.

Design (deliberately low false-positive):
  1. Binary/attachment extensions (scanned PDFs, photos, spreadsheets) are BLOCKED
     anywhere — a real report would arrive as one of these and must never enter
     the repo.
  2. Real-data text sentinels (the client org name, etc.) are scanned ONLY in
     data-bearing files. Source code, docs, and config legitimately reference the
     org name (it is the subject of the project), and files under data/synthetic/
     are synthetic by construction — both are exempt from the text scan. A stray
     real report pasted as e.g. report.txt or data/raw/x.csv is still caught.
"""

from __future__ import annotations

import re
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

# Binary / attachment extensions that should never be committed (real scans etc.).
_BINARY_EXT = re.compile(r"\.(pdf|jpe?g|png|webp|tiff?|bmp|gif|xlsx?|docx?|pptx?)$", re.IGNORECASE)

# SQLite databases (the approval-gate store) can accrue real PII — allowed only in
# private/ (gitignored). Blocked as an extension wherever this guard inspects a file.
# Covers the whole SQLite family: base .db/.db3, .s3db, .sqlite/.sqlite2/.sqlite3, each
# with an OPTIONAL -wal/-shm/-journal sidecar (SQLite names sidecars <dbfile>-wal, so a
# .sqlite3 DB yields app.sqlite3-wal). Keep in sync with preflight.py's `_DB_RE`.
_DB_EXT = re.compile(r"\.(db3?|s3db|sqlite[23]?)(-(wal|shm|journal))?$", re.IGNORECASE)

# Real-data text sentinels — patterns that should not appear in *data* files.
_TEXT_SENTINELS: list[re.Pattern[str]] = [
    re.compile(r"\bHT\s*Micron\b", re.IGNORECASE),
    re.compile(r"\bhtmicron\b", re.IGNORECASE),
]

# Extensions exempt from the TEXT scan (they may mention the org name legitimately).
# The binary-extension block above still applies to everything.
_SOURCE_DOC_EXT = {
    ".py",
    ".md",
    ".rst",
    ".yaml",
    ".yml",
    ".toml",
    ".cfg",
    ".ini",
    ".j2",
    ".jinja",
    ".jinja2",
    ".html",
    ".htm",
    ".css",
    ".js",
    ".ts",
    ".gitignore",
    ".gitkeep",
}

# Path components under which content is synthetic by construction (text-scan exempt).
_SYNTHETIC_SUBPATH = ("data", "synthetic")

# Directory holding committed synthetic sample media for product inspection.
# Known files here are allowed despite the global binary block — they are generated
# by our code from synthetic data, never real scans. Paths alone are not evidence of
# provenance: every exception is pinned to the SHA-256 of the reviewed public asset.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SAMPLES_DIR = Path("samples")
_ALLOWED_SAMPLE_SHA256: dict[Path, str] = {
    _SAMPLES_DIR / "cockpit_demo.gif": (
        "8a47705ac65f835107d4aa11ac2f72254c0ddaaf2fc3b0f456c7ae25868ee4fe"
    ),
    _SAMPLES_DIR / "review_approved.png": (
        "aea6ac9033397d2106f6b391077113ebc185952807940e1ed928df768e321acc"
    ),
    _SAMPLES_DIR / "sample_tc-000000.png": (
        "b31a545e88a412cf370af0b400582bec7eb7e61d22d4434f859048cb5ac69084"
    ),
}


def _is_root_subpath(path: Path, parts: tuple[str, ...]) -> bool:
    """True only when *parts* anchors the repository-relative path."""
    return path.parts[: len(parts)] == parts


def _file_sha256(path: Path) -> str | None:
    """Return a file digest, or ``None`` when the candidate cannot be read."""
    digest = sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _is_allowed_sample_binary(path: Path, *, repository_relative_path: Path | None = None) -> bool:
    """Match a reviewed sample by exact repository path and SHA-256.

    ``repository_relative_path`` lets a caller scanning an injected repository root
    provide the logical path separately from the physical file being hashed. The
    production pre-commit path does not need it: relative arguments are repository
    paths and absolute arguments must resolve inside this checkout.
    """
    physical = path if path.is_absolute() else path.resolve()
    if repository_relative_path is not None:
        relative = repository_relative_path
    elif path.is_absolute():
        try:
            relative = physical.relative_to(_REPO_ROOT)
        except ValueError:
            return False
    else:
        relative = path

    expected = _ALLOWED_SAMPLE_SHA256.get(relative)
    return expected is not None and _file_sha256(physical) == expected


def _is_text_scan_exempt(path: Path) -> bool:
    if path.suffix.lower() in _SOURCE_DOC_EXT:
        return True
    if path.name in _SOURCE_DOC_EXT:  # e.g. ".gitignore" has no suffix
        return True
    return _is_root_subpath(path, _SYNTHETIC_SUBPATH)


def _logical_path(path: Path) -> Path:
    if not path.is_absolute():
        return path
    try:
        return path.resolve().relative_to(_REPO_ROOT)
    except ValueError:
        return path


def check_content(path: Path, content: bytes) -> list[str]:
    """Check repository-relative *path* using the exact supplied bytes."""
    violations: list[str] = []
    logical_path = _logical_path(path)

    expected_sample_hash = _ALLOWED_SAMPLE_SHA256.get(logical_path)
    allowed_sample = expected_sample_hash == sha256(content).hexdigest()
    if _BINARY_EXT.search(path.name):
        if not allowed_sample:
            violations.append(f"  {path}: binary/attachment extension not allowed in repo")
        return violations

    if _DB_EXT.search(path.name):
        violations.append(f"  {path}: database file not allowed in repo (belongs in private/)")
        return violations

    if _is_text_scan_exempt(logical_path):
        return []

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return [f"  {path}: text content is not valid UTF-8"]
    for pattern in _TEXT_SENTINELS:
        for lineno, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                violations.append(f"  {path}:{lineno}: matched real-data sentinel")

    return violations


def check_file(path: Path) -> list[str]:
    """Check worktree bytes for unit-level and standalone callers."""
    try:
        content = path.read_bytes()
    except OSError:
        return [f"  {path}: content could not be read"]
    return check_content(path, content)


def staged_paths(repo_root: Path = _REPO_ROOT) -> list[Path]:
    """Return added/copied/modified/renamed destination paths from the Git index."""
    output = subprocess.run(
        [
            "git",
            "diff",
            "--cached",
            "--name-only",
            "--diff-filter=ACMR",
            "-z",
            "--",
        ],
        cwd=repo_root,
        check=True,
        capture_output=True,
    ).stdout
    return [Path(raw.decode("utf-8")) for raw in output.split(b"\0") if raw]


def staged_blob(path: Path, repo_root: Path = _REPO_ROOT) -> bytes:
    """Read *path* from the index, never from a potentially divergent worktree."""
    return subprocess.run(
        ["git", "cat-file", "blob", f":{path.as_posix()}"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    ).stdout


def check_staged(repo_root: Path = _REPO_ROOT) -> list[str]:
    """Check every committable staged blob, including rename destinations."""
    violations: list[str] = []
    try:
        paths = staged_paths(repo_root)
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        return ["  Git index could not be enumerated safely"]
    for path in paths:
        try:
            content = staged_blob(path, repo_root)
        except (OSError, subprocess.SubprocessError):
            violations.append(f"  {path}: staged content could not be read")
            continue
        violations.extend(check_content(path, content))
    return violations


def main(argv: list[str]) -> int:
    # Older hooks pass worktree paths. Ignore those selectors: the index is
    # authoritative, and scanning every staged ACMR blob includes rename destinations.
    _ = argv
    all_violations = check_staged()

    if all_violations:
        print("BLOCKED: possible real data detected in staged files:", file=sys.stderr)
        for v in all_violations:
            print(v, file=sys.stderr)
        print(
            "\nIf this is synthetic/source content (a false positive), see the design "
            "notes in scripts/check_real_data.py — source/docs/config and data/synthetic/ "
            "are exempt from the text scan.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
