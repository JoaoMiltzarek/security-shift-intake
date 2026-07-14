"""Contratos operacionais do Makefile em shells Windows e POSIX."""

from __future__ import annotations

import re
from pathlib import Path

import pytest


def test_python_recipes_do_not_depend_on_posix_env_assignment() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    assert "PYTHONPATH=." not in makefile
    assert "uv run --locked python -m scripts.purge_demo_data demo" in makefile


def test_uv_recipes_fail_closed_when_lockfile_is_stale() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    uv_run_recipes = [
        line.strip() for line in makefile.splitlines() if line.startswith("\tuv run ")
    ]
    assert uv_run_recipes
    assert all(line.startswith("uv run --locked ") for line in uv_run_recipes)
    assert "\tuv sync --locked" in makefile


def test_release_safety_targets_share_one_fixed_dataset_contract() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    assert "override SAFETY_DATASET := bench-balanced" in makefile
    assert "override SAFETY_SPLIT := val" in makefile

    generate = re.search(r"(?ms)^gen-safety-sheets:\s*\n(?P<body>(?:\t.*\n?)+)", makefile)
    gate = re.search(r"(?ms)^eval-safety:\s*\n(?P<body>(?:\t.*\n?)+)", makefile)
    assert generate is not None and gate is not None
    assert "--dataset $(SAFETY_DATASET)" in generate.group("body")
    assert "--dataset $(SAFETY_DATASET)" in gate.group("body")
    assert "--split $(SAFETY_SPLIT)" in gate.group("body")
    assert "$(SPLIT)" not in gate.group("body")
    assert '--output-dir "$(OUT)"' in gate.group("body")


def test_release_safety_target_freezes_real_ocr_reader() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    gate = re.search(r"(?ms)^eval-safety:\s*\n(?P<body>(?:\t.*\n?)+)", makefile)

    assert "override SAFETY_VISION := local_ocr" in makefile
    assert gate is not None
    assert "--vision $(SAFETY_VISION)" in gate.group("body")
    assert "--vision $(VISION)" not in gate.group("body")


@pytest.mark.xfail(strict=True, reason="make check ainda não bloqueia formatação divergente")
def test_check_includes_format_gate() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "check: format-check lint typecheck test" in makefile
