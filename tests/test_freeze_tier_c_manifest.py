"""Explicit, write-once release workflow for the Tier C v2 freeze."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from data.tier_c_contract import TierCContractError, TierCManifestEntry, canonical_manifest_bytes
from scripts import freeze_tier_c_manifest as freeze


def _verified() -> SimpleNamespace:
    entry = TierCManifestEntry(
        doc_id="tc-000001",
        split="val",
        image="pngs/tc-000001.png",
        gt="gt/tc-000001.json",
        sha256_img="a" * 64,
        sha256_gt="b" * 64,
    )
    return SimpleNamespace(entries=(entry,), manifest_sha256="c" * 64)


def test_freeze_creates_missing_manifest_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "frozen" / "bench-balanced.val.jsonl"
    verified = _verified()
    monkeypatch.setattr(freeze, "default_frozen_manifest_path", lambda *_args: destination)
    monkeypatch.setattr(freeze, "load_verified_canonical_split", lambda *_args, **_kwargs: verified)

    assert (
        freeze.main(
            [
                "--dir",
                str(tmp_path / "dataset with spaces"),
                "--dataset",
                "bench-balanced",
                "--split",
                "val",
                "--write",
            ]
        )
        == 0
    )
    assert destination.read_bytes() == canonical_manifest_bytes(verified.entries)


def test_freeze_accepts_identical_existing_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "bench-balanced.val.jsonl"
    verified = _verified()
    destination.write_bytes(canonical_manifest_bytes(verified.entries))
    monkeypatch.setattr(freeze, "default_frozen_manifest_path", lambda *_args: destination)
    monkeypatch.setattr(freeze, "load_verified_canonical_split", lambda *_args, **_kwargs: verified)

    assert (
        freeze.main(
            [
                "--dir",
                str(tmp_path / "dataset"),
                "--dataset",
                "bench-balanced",
                "--split",
                "val",
                "--write",
            ]
        )
        == 0
    )


def test_freeze_refuses_to_overwrite_different_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    destination = tmp_path / "bench-balanced.val.jsonl"
    destination.write_text("different\n", encoding="utf-8")
    monkeypatch.setattr(freeze, "default_frozen_manifest_path", lambda *_args: destination)
    monkeypatch.setattr(
        freeze, "load_verified_canonical_split", lambda *_args, **_kwargs: _verified()
    )

    assert (
        freeze.main(
            [
                "--dir",
                str(tmp_path / "dataset"),
                "--dataset",
                "bench-balanced",
                "--split",
                "val",
                "--write",
            ]
        )
        == 1
    )
    assert destination.read_text(encoding="utf-8") == "different\n"
    assert "RECUSADO" in capsys.readouterr().err


def test_freeze_does_not_write_when_source_contract_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    destination = tmp_path / "bench-balanced.val.jsonl"
    monkeypatch.setattr(freeze, "default_frozen_manifest_path", lambda *_args: destination)

    def invalid(*_args: object, **_kwargs: object) -> object:
        raise TierCContractError("invalid synthetic source")

    monkeypatch.setattr(freeze, "load_verified_canonical_split", invalid)

    assert (
        freeze.main(
            [
                "--dir",
                str(tmp_path / "dataset"),
                "--dataset",
                "bench-balanced",
                "--split",
                "val",
                "--write",
            ]
        )
        == 1
    )
    assert not destination.exists()
    assert "CONTRATO TIER C INVÁLIDO" in capsys.readouterr().err
