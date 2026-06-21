"""Pre-commit guard: reject staged files containing patterns that suggest real data.

Called by the pre-commit hook. Exits 0 (clean) or 1 (suspicious patterns found).
Also usable standalone: python scripts/check_real_data.py <file> [<file> ...]

§9 risk: confidential data leak — real HT Micron reports/names committed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Patterns that strongly suggest real operational data slipped in.
# Deliberately conservative: false positives are cheap, false negatives are not.
_SUSPICIOUS: list[re.Pattern[str]] = [
    re.compile(r"\bHT\s*Micron\b", re.IGNORECASE),
    re.compile(r"\bhtmicron\b", re.IGNORECASE),
    # Binary attachment extensions that should never enter the repo.
    re.compile(r"\.(pdf|jpg|jpeg|png|tiff?|bmp|xlsx?|docx?)$", re.IGNORECASE),
]

# Files whose content is known-safe to skip. Includes:
# - Documentation that intentionally names the client org.
# - The guard script itself and its tests (they reference patterns, not real data).
_ALLOWLISTED_PATHS: set[str] = {
    "PROJECT_SPEC.md",
    "CLAUDE.md",
    "README.md",
    "check_real_data.py",       # this script — patterns are strings, not data
    "test_real_data_guard.py",  # test fixtures that reference patterns
}


def check_file(path: Path) -> list[str]:
    """Return a list of violation descriptions for *path*, empty if clean."""
    violations: list[str] = []

    # Allow-list by filename (not full path) for known-safe docs.
    if path.name in _ALLOWLISTED_PATHS:
        return []

    # Binary / attachment extension check (path alone, no content read needed).
    for pat in _SUSPICIOUS:
        if pat.search(str(path)) and pat.pattern.startswith(r"\."):
            violations.append(f"  {path}: binary/attachment extension not allowed in repo")
            return violations  # no need to read content

    # Text content check — skip non-text files gracefully.
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    for pat in _SUSPICIOUS:
        if pat.pattern.startswith(r"\."):
            continue  # already handled above
        for lineno, line in enumerate(text.splitlines(), 1):
            if pat.search(line):
                violations.append(
                    f"  {path}:{lineno}: matched pattern {pat.pattern!r} -> {line.strip()!r}"
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
            "\nIf this is a false positive, add the file to _ALLOWLISTED_PATHS in "
            "scripts/check_real_data.py and re-commit.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
