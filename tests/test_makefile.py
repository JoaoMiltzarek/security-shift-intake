"""Contratos operacionais do Makefile em shells Windows e POSIX."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_python_recipes_do_not_depend_on_posix_env_assignment() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    assert "PYTHONPATH=." not in makefile
    assert "uv run python -m scripts.purge_demo_data demo" in makefile


@pytest.mark.xfail(
    strict=True,
    reason="SSI-1011: receitas uv ainda podem re-resolver um lock inconsistente",
)
def test_uv_recipes_fail_closed_when_lockfile_is_stale() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    uv_run_recipes = [
        line.strip() for line in makefile.splitlines() if line.startswith("\tuv run ")
    ]
    assert uv_run_recipes
    assert all(line.startswith("uv run --locked ") for line in uv_run_recipes)
    assert "\tuv sync --locked" in makefile
