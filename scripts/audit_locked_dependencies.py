"""Audit the dependency graph encoded by uv.lock instead of the ambient venv."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def audit_locked_dependencies() -> int:
    """Export hashed requirements from uv.lock and return pip-audit's status."""
    with tempfile.TemporaryDirectory(prefix="ssi-dependency-audit-") as temp_dir:
        requirements = Path(temp_dir) / "requirements.txt"
        subprocess.run(
            [
                "uv",
                "export",
                "--locked",
                "--format",
                "requirements.txt",
                "--no-emit-project",
                "--output-file",
                str(requirements),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip_audit",
                "--requirement",
                str(requirements),
                "--strict",
                "--progress-spinner",
                "off",
                "--disable-pip",
            ],
            check=False,
        )
        return result.returncode


def main() -> int:
    return audit_locked_dependencies()


if __name__ == "__main__":
    raise SystemExit(main())
