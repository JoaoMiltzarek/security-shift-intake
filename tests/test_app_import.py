"""Importing the FastAPI factory must never open or migrate the operational DB."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from src.paths import REPO_ROOT


def test_importing_app_factory_has_no_database_side_effect(tmp_path: Path) -> None:
    database = tmp_path / "must-not-exist.db"
    env = os.environ.copy()
    env["INTAKE_DB_URL"] = f"sqlite:///{database.as_posix()}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    result = subprocess.run(
        [sys.executable, "-c", "import src.api.app"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert not database.exists()
