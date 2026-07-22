"""CLI entry point for `make validate-config`.

Usage:
    python scripts/validate_config.py configs/controle_ocorrencias.yaml

Exits 0 on success, 1 on validation error.
"""

from __future__ import annotations

import sys
from pathlib import Path

from pydantic import ValidationError

from src.schema.loader import load_config


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: validate_config.py <config.yaml> [<config.yaml> ...]", file=sys.stderr)
        return 2

    ok = True
    for arg in argv:
        path = Path(arg)
        try:
            cfg = load_config(path)
            print(f"OK  {path}  (report_type={cfg.report_type!r}, fields={len(cfg.fields)})")
        except FileNotFoundError:
            print(f"ERR {path}: file not found", file=sys.stderr)
            ok = False
        except ValidationError as exc:
            print(f"ERR {path}: validation failed", file=sys.stderr)
            print(exc, file=sys.stderr)
            ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
