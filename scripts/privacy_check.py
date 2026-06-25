"""Privacy guardrail — run anytime to confirm no real data leaked (plan R4 / retention).

Three checks, all aborting with exit 1 on any violation:
  (1) No sensitive binary/data file is *git-tracked* (real sheets, scans, audit JSON).
      Reuses the binary-extension rule from `check_real_data` (the pre-commit guard).
  (2) No sensitive binary file sits *outside* `private/` in the working tree (a real
      sheet must live only in `private/`, which is gitignored).
  (3) No public text output (README, EVAL_REPORT.md, docs/*.md, configs/*.yaml) contains
      obvious PII: the org sentinel, a clock time `HH:MM` (real shift times), or any term
      listed in the optional, gitignored `private/pii_terms.txt` (real names etc.).

The report writers import `scan_text_for_pii` and abort before writing if it returns hits
— a public artifact is never generated with PII in it (plan R4).

Standalone: `python scripts/privacy_check.py` → exit 0 (clean) or 1 (violations).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from scripts.check_real_data import (
    _BINARY_EXT,
    _SYNTHETIC_SUBPATH,
    _has_subpath,
    _is_allowed_sample_image,
    _is_text_scan_exempt,
)

# Directories that never hold committable source and are skipped by the tree scan.
_SKIP_DIRS = {".git", ".venv", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}

# The private folder is gitignored and is the ONLY place real data may live.
_PRIVATE_DIR = "private"

# Synthetic sample images committed for eyeballing are allowed (generated, not real).
_SAMPLES_DIR = "samples"

# Public text files scanned for PII. Extensions whose content is human-facing/committed.
_PUBLIC_TEXT_EXT = {".md", ".yaml", ".yml", ".txt", ".rst"}

# Optional, gitignored file with real terms (names, units) to scan public outputs for.
_PII_TERMS_FILE = Path(_PRIVATE_DIR) / "pii_terms.txt"

# Org sentinels — like check_real_data, only flagged where the org name is NOT a
# legitimate mention (i.e. not in source/docs/config, which are about the org).
_ORG_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bHT\s*Micron\b", re.IGNORECASE),
    re.compile(r"\bhtmicron\b", re.IGNORECASE),
]

# A clock time that is NOT part of an ISO timestamp (real sheet times are HH:MM with no
# seconds; ISO has HH:MM:SS and tz offsets) — always sensitive in a public output.
_TIME_PATTERN = re.compile(r"(?<![\d:+-])\d{1,2}:\d{2}(?!:?\d)")


def _load_extra_terms() -> list[re.Pattern[str]]:
    """Compile case-insensitive patterns from the optional private PII-terms file."""
    if not _PII_TERMS_FILE.exists():
        return []
    patterns: list[re.Pattern[str]] = []
    for line in _PII_TERMS_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        term = line.strip()
        if term and not term.startswith("#"):
            patterns.append(re.compile(re.escape(term), re.IGNORECASE))
    return patterns


def scan_text_for_pii(
    text: str,
    extra_terms: list[re.Pattern[str]] | None = None,
    include_org: bool = True,
) -> list[str]:
    """Return PII snippets in *text* (HH:MM times, private terms, and org if include_org)."""
    org = list(_ORG_PATTERNS) if include_org else []
    patterns = (
        org + [_TIME_PATTERN] + (extra_terms if extra_terms is not None else _load_extra_terms())
    )
    hits: list[str] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for pat in patterns:
            m = pat.search(line)
            if m:
                hits.append(f"  line {lineno}: {pat.pattern!r} -> {m.group(0)!r}")
    return hits


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    ).stdout
    return [Path(p) for p in out.splitlines() if p.strip()]


def check_no_sensitive_tracked() -> list[str]:
    """(1) No git-tracked file has a sensitive binary extension (except sample images)."""
    violations: list[str] = []
    for path in _tracked_files():
        if _BINARY_EXT.search(path.name) and not _is_allowed_sample_image(path):
            violations.append(f"  tracked sensitive file: {path}")
    return violations


def _iter_tree(root: Path) -> list[Path]:
    files: list[Path] = []
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        files.append(p)
    return files


def check_no_sensitive_outside_private(root: Path = Path(".")) -> list[str]:
    """(2) No sensitive binary file sits outside private/.

    Allowed: synthetic sample images under samples/ and generated synthetic artifacts
    under data/synthetic/ (both synthetic by construction, the latter gitignored).
    """
    violations: list[str] = []
    for p in _iter_tree(root):
        rel = p.relative_to(root) if p.is_absolute() else p
        if _PRIVATE_DIR in rel.parts or _has_subpath(rel, _SYNTHETIC_SUBPATH):
            continue
        if _BINARY_EXT.search(p.name) and not _is_allowed_sample_image(rel):
            violations.append(f"  sensitive file outside {_PRIVATE_DIR}/: {rel}")
    return violations


def check_public_no_pii(root: Path = Path(".")) -> list[str]:
    """(3) No committable public text file contains obvious PII."""
    extra = _load_extra_terms()
    violations: list[str] = []
    for p in _iter_tree(root):
        rel = p.relative_to(root) if p.is_absolute() else p
        if _PRIVATE_DIR in rel.parts or _SAMPLES_DIR in rel.parts:
            continue
        if p.suffix.lower() not in _PUBLIC_TEXT_EXT:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Source/docs/config legitimately name the org (it is the project's subject);
        # exempt them from the org sentinel exactly like the pre-commit guard does.
        include_org = not _is_text_scan_exempt(rel)
        hits = scan_text_for_pii(text, extra_terms=extra, include_org=include_org)
        violations.extend(f"  {rel}:{h.strip()}" for h in hits)
    return violations


def run_all(root: Path = Path(".")) -> list[str]:
    return (
        check_no_sensitive_tracked()
        + check_no_sensitive_outside_private(root)
        + check_public_no_pii(root)
    )


def main(argv: list[str]) -> int:
    violations = run_all()
    if violations:
        print("PRIVACY-CHECK FAILED — possible real data / PII detected:", file=sys.stderr)
        for v in violations:
            print(v, file=sys.stderr)
        print(
            "\nReal sheets/curadoria/audit live ONLY in private/ (gitignored). "
            "Public outputs must carry aggregate metrics + synthetic examples only.",
            file=sys.stderr,
        )
        return 1
    print("privacy-check OK — no real data tracked, none outside private/, no PII in public files.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
