"""Contracts for read-only validation of the corpus-and-pin checkpoint."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from data.safety_corpus import SAFETY_COUNT
from data.tier_c_contract import TierCContractError
from scripts import verify_safety_corpus_checkpoint as verifier

COMMIT = "a" * 40


def _checkpoint(root: Path) -> tuple[Path, Path]:
    root.mkdir()
    corpus = root / verifier.CORPUS_MEMBER
    corpus.mkdir()
    pin = root / verifier.PIN_MEMBER
    pin.write_text("pin\n", encoding="utf-8")
    return corpus, pin


def _verified(*, count: int = SAFETY_COUNT, commit: str = COMMIT) -> Any:
    return SimpleNamespace(
        split=SimpleNamespace(entries=tuple(object() for _ in range(count))),
        provenance=SimpleNamespace(
            generator_commit=commit,
            logical_freeze_sha256="b" * 64,
            manifest_sha256="c" * 64,
        ),
    )


def test_checkpoint_verifier_uses_the_sibling_pin_and_current_freeze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint = tmp_path / "checkpoint"
    corpus, pin = _checkpoint(checkpoint)
    observed: list[tuple[Path, Path, Path]] = []

    def load(root: Path, *, pin_path: Path, logical_freeze_path: Path) -> Any:
        observed.append((root, pin_path, logical_freeze_path))
        return _verified()

    monkeypatch.setattr(verifier, "load_verified_safety_corpus", load)
    monkeypatch.setattr(verifier, "_git_commit", lambda: COMMIT)
    before = pin.read_bytes()

    result = verifier.verify_checkpoint(checkpoint)

    assert len(result.split.entries) == SAFETY_COUNT
    assert observed == [(corpus, pin, verifier.SAFETY_LOGICAL_FREEZE)]
    assert pin.read_bytes() == before


def test_checkpoint_verifier_rejects_extra_top_level_members(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint"
    _checkpoint(checkpoint)
    (checkpoint / "extra.txt").write_text("extra\n", encoding="utf-8")

    with pytest.raises(TierCContractError, match="members are not exact"):
        verifier.verify_checkpoint(checkpoint)


def test_checkpoint_verifier_rejects_wrong_count_or_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint = tmp_path / "checkpoint"
    _checkpoint(checkpoint)
    monkeypatch.setattr(verifier, "_git_commit", lambda: COMMIT)
    monkeypatch.setattr(
        verifier,
        "load_verified_safety_corpus",
        lambda *_args, **_kwargs: _verified(count=SAFETY_COUNT - 1),
    )
    with pytest.raises(TierCContractError, match="44 sheets, expected 45"):
        verifier.verify_checkpoint(checkpoint)

    monkeypatch.setattr(
        verifier,
        "load_verified_safety_corpus",
        lambda *_args, **_kwargs: _verified(commit="d" * 40),
    )
    with pytest.raises(TierCContractError, match="commit differs"):
        verifier.verify_checkpoint(checkpoint)


def test_checkpoint_verifier_cli_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert verifier.main(["--checkpoint", str(tmp_path / "missing")]) == 1
    assert "SAFETY CORPUS CHECKPOINT REFUSED" in capsys.readouterr().err
