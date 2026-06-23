"""Wipe real demo data — remove everything under `private/`.

`private/` is the gitignored folder holding real input sheets and the local SQLite
DB (which contains PII from a real test). Run after a demo to leave no real data on
disk. Operations are restricted to `private/` — nothing outside it is touched.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

PRIVATE_DIR = Path("private")


def purge(directory: Path = PRIVATE_DIR) -> list[str]:
    """Delete every entry inside *directory* (not the directory itself). Returns names."""
    removed: list[str] = []
    if not directory.exists():
        return removed
    for entry in directory.iterdir():
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()
        removed.append(entry.name)
    return removed


def main(argv: list[str]) -> int:
    removed = purge()
    if removed:
        print(f"Removed {len(removed)} item(s) from {PRIVATE_DIR}/: {', '.join(removed)}")
    else:
        print(f"Nothing to remove ({PRIVATE_DIR}/ is empty or absent).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
