"""CLI contracts for canonical Tier C generation."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import gen_sheets


@pytest.mark.parametrize("option", ["--seed", "--n", "--profile", "--split-seed"])
def test_cli_rejects_overrides_for_named_datasets(tmp_path: Path, option: str) -> None:
    values = {
        "--seed": "42",
        "--n": "50",
        "--profile": "balanced",
        "--split-seed": "0",
    }

    with pytest.raises(SystemExit) as exc_info:
        gen_sheets.main(
            ["--dataset", "smoke", option, values[option], "--out", str(tmp_path / "out")]
        )

    assert exc_info.value.code == 2
    assert not (tmp_path / "out").exists()
