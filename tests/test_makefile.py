"""Contratos operacionais do Makefile em shells Windows e POSIX."""

from __future__ import annotations

from pathlib import Path


def test_python_recipes_do_not_depend_on_posix_env_assignment() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    assert "PYTHONPATH=." not in makefile
    assert "uv run python -m scripts.purge_demo_data demo" in makefile
