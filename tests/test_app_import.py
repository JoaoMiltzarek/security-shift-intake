"""Importing the FastAPI factory must never open or migrate the operational DB."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from statistics import median

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


def test_app_factory_cold_import_stays_within_startup_budget() -> None:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    durations: list[float] = []

    for _ in range(5):
        started_at = time.perf_counter()
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; import src.api.app; "
                    "assert not any(name == 'sklearn' or name.startswith('sklearn.') "
                    "for name in sys.modules)"
                ),
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        durations.append(time.perf_counter() - started_at)
        assert result.returncode == 0, result.stderr

    assert median(durations) <= 4.0, (
        f"cold import median exceeded the 4 s budget: {median(durations):.3f} s ({durations!r})"
    )
