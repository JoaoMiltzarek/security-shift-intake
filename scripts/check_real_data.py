"""Pre-commit guard: reject staged files that look like real (non-synthetic) data.

Called by the pre-commit hook. Exits 0 (clean) or 1 (suspicious patterns found).
Also usable standalone: python scripts/check_real_data.py <file> [<file> ...]

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
import sys
from hashlib import sha256
from pathlib import Path

# Binary / attachment extensions that should never be committed (real scans etc.).
_BINARY_EXT = re.compile(r"\.(pdf|jpe?g|png|tiff?|bmp|gif|xlsx?|docx?|pptx?)$", re.IGNORECASE)

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
    ".py", ".md", ".rst",
    ".yaml", ".yml", ".toml", ".cfg", ".ini",
    ".j2", ".jinja", ".jinja2",
    ".html", ".htm", ".css", ".js", ".ts",
    ".gitignore", ".gitkeep",
}

# Path components under which content is synthetic by construction (text-scan exempt).
_SYNTHETIC_SUBPATH = ("data", "synthetic")

# Directory holding committed SYNTHETIC sample media for eyeballing (Tier B output).
# Known files here are allowed despite the global binary block — they are generated
# by our code from synthetic data, never real scans. Paths alone are not evidence of
# provenance: every exception is pinned to the SHA-256 of the reviewed public asset.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SAMPLES_DIR = Path("samples")
_ALLOWED_SAMPLE_SHA256: dict[Path, str] = {
    _SAMPLES_DIR / "cockpit_demo.gif": (
        "1cb6b0e320cdf4b6fc743a0cd61c370bf3b1bb1d2b538324088561402cdc9151"
    ),
    _SAMPLES_DIR / "sample_doc-00000.png": (
        "b171955288e063106856e9442e0c91166b51a1dac9494452eb54fde321811d57"
    ),
    _SAMPLES_DIR / "sample_doc-00001.png": (
        "d399d50a25b252f39e3c1e663edbf7fa8d3230dafaf9cc273e98e1e90b6d3d9b"
    ),
    _SAMPLES_DIR / "sample_tc-000000.png": (
        "b31a545e88a412cf370af0b400582bec7eb7e61d22d4434f859048cb5ac69084"
    ),
    _SAMPLES_DIR / "sample_tc-000001.png": (
        "29e4505c8316a7c80b47437867f8f3c9e36b56f8802d62175720329e9627510e"
    ),
}


def _has_subpath(path: Path, parts: tuple[str, ...]) -> bool:
    """True if *parts* appears as a contiguous run in path.parts."""
    p = path.parts
    n = len(parts)
    return any(p[i : i + n] == parts for i in range(len(p) - n + 1))


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


def _is_allowed_sample_binary(
    path: Path, *, repository_relative_path: Path | None = None
) -> bool:
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
    return _has_subpath(path, _SYNTHETIC_SUBPATH)


def check_file(path: Path) -> list[str]:
    """Return a list of violation descriptions for *path*, empty if clean."""
    violations: list[str] = []

    # (1) Binary/attachment extensions — blocked everywhere, EXCEPT synthetic sample
    # images explicitly committed under samples/.
    if _BINARY_EXT.search(path.name) and not _is_allowed_sample_binary(path):
        violations.append(f"  {path}: binary/attachment extension not allowed in repo")
        return violations  # no need to read content

    # (1b) SQLite databases belong only in private/ (gitignored). The extension is
    # blocked wherever seen; private/ safety comes from .gitignore, not this check.
    if _DB_EXT.search(path.name):
        violations.append(f"  {path}: database file not allowed in repo (belongs in private/)")
        return violations

    # (2) Text sentinels — only in data-bearing files.
    if _is_text_scan_exempt(path):
        return []

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    for pat in _TEXT_SENTINELS:
        for lineno, line in enumerate(text.splitlines(), 1):
            if pat.search(line):
                violations.append(
                    f"  {path}:{lineno}: matched real-data sentinel"
                )

    return violations


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: check_real_data.py <file> [<file> ...]", file=sys.stderr)
        return 2

    all_violations: list[str] = []
    for arg in argv:
        all_violations.extend(check_file(Path(arg)))

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
