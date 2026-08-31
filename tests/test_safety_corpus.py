"""Contracts for the committed v1.1 structural-safety corpus."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from data.generators.tier_c import DATASET_VERSION, MANIFEST_SCHEMA
from data.safety_corpus import (
    CORPUS_SCHEMA,
    EXPECTED_PYTHON,
    EXPECTED_TESSERACT_PACKAGE,
    EXPECTED_TESSERACT_POR_PACKAGE,
    EXPECTED_UBUNTU,
    EXPECTED_UV,
    INVENTORY_PIN_TARGET,
    RELEASE_LINE,
    SAFETY_COUNT,
    SAFETY_DATASET,
    SAFETY_SPLIT,
    SafetyCorpusProvenance,
    inventory_bytes,
    inventory_pin_bytes,
    load_verified_safety_corpus,
    parse_inventory_pin,
    uv_release_version,
)
from data.tier_c_contract import TierCContractError


def _provenance() -> dict[str, object]:
    commit = "a" * 40
    return {
        "corpus_schema": CORPUS_SCHEMA,
        "release_line": RELEASE_LINE,
        "dataset": SAFETY_DATASET,
        "split": SAFETY_SPLIT,
        "count": SAFETY_COUNT,
        "dataset_version": DATASET_VERSION,
        "manifest_schema": MANIFEST_SCHEMA,
        "logical_freeze_sha256": "e" * 64,
        "manifest_sha256": "b" * 64,
        "generator_commit": commit,
        "generated_meta_commit": commit,
        "created_at_utc": "20260821T120000Z",
        "python_version": EXPECTED_PYTHON,
        "uv_version": EXPECTED_UV,
        "pillow_version": "12.2.0",
        "uv_lock_sha256": "c" * 64,
        "ubuntu_id": "ubuntu",
        "ubuntu_version": EXPECTED_UBUNTU,
        "runner_image": "ubuntu24",
        "runner_image_version": "20260817.1",
        "tesseract_package_version": EXPECTED_TESSERACT_PACKAGE,
        "tesseract_por_package_version": EXPECTED_TESSERACT_POR_PACKAGE,
        "tesseract_engine_version": "5.3.4",
        "tesseract_language": "por",
        "github_repository": "JoaoMiltzarek/security-shift-intake",
        "github_workflow_ref": (
            "JoaoMiltzarek/security-shift-intake/.github/workflows/"
            "build-safety-corpus.yml@refs/heads/main"
        ),
        "github_sha": commit,
        "github_run_id": "123",
        "github_run_attempt": "1",
        "font_files": [{"path": "assets/fonts/Hand.ttf", "sha256": "d" * 64}],
    }


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("uv 0.11.28", "0.11.28"),
        (
            "uv 0.11.28 (ebf0f43d7 2026-07-07 x86_64-unknown-linux-gnu)",
            "0.11.28",
        ),
        ("uv 0.11.28 unexpected-suffix", None),
        ("uv 0.11.28 ()", None),
        ("uv 0.11.28 (unterminated", None),
        ("uv 0.11.28 (metadata\ncontinued)", None),
        ("0.11.28", None),
    ],
)
def test_uv_release_version_accepts_only_supported_cli_shapes(
    output: str, expected: str | None
) -> None:
    assert uv_release_version(output) == expected


def test_provenance_is_closed_and_binds_all_build_commits() -> None:
    provenance = SafetyCorpusProvenance.model_validate(_provenance())
    assert provenance.generator_commit == provenance.github_sha
    assert provenance.logical_freeze_sha256 != provenance.manifest_sha256

    extra = {**_provenance(), "unreviewed": True}
    with pytest.raises(ValidationError, match="extra_forbidden"):
        SafetyCorpusProvenance.model_validate(extra)
    divergent = {**_provenance(), "github_sha": "e" * 40}
    with pytest.raises(ValidationError, match="commits must agree"):
        SafetyCorpusProvenance.model_validate(divergent)
    missing_freeze = _provenance()
    missing_freeze.pop("logical_freeze_sha256")
    with pytest.raises(ValidationError, match="Field required"):
        SafetyCorpusProvenance.model_validate(missing_freeze)


def test_inventory_is_utf8_lf_sorted_and_rejects_escape() -> None:
    hashes = {
        "pngs/tc-000001.png": hashlib.sha256(b"png").hexdigest(),
        "gt/tc-000001.json": hashlib.sha256(b"gt").hexdigest(),
    }

    content = inventory_bytes(hashes)

    assert content.endswith(b"\n")
    assert b"\r" not in content
    paths = [line.split("  ", 1)[1] for line in content.decode().splitlines()]
    assert paths == sorted(paths)
    with pytest.raises(ValueError, match="invalid corpus inventory member"):
        inventory_bytes({"../escape": "a" * 64})


def test_external_inventory_pin_is_canonical_and_rejects_invalid_hash() -> None:
    digest = "a" * 64

    assert inventory_pin_bytes(digest) == f"{digest}  {INVENTORY_PIN_TARGET}\n".encode()
    assert parse_inventory_pin(inventory_pin_bytes(digest)) == digest
    with pytest.raises(ValueError, match="invalid safety corpus inventory pin"):
        inventory_pin_bytes("A" * 64)
    with pytest.raises(TierCContractError, match="pin is invalid"):
        parse_inventory_pin(inventory_pin_bytes(digest).replace(b"\n", b"\r\n"))


def test_public_loader_requires_matching_external_inventory_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import data.safety_corpus as corpus

    root = tmp_path / "bench-balanced-val"
    root.mkdir()
    inventory = b"authenticated inventory\n"
    (root / "SHA256SUMS").write_bytes(inventory)
    pin = tmp_path / "bench-balanced-val.SHA256SUMS.sha256"
    pin.write_bytes(inventory_pin_bytes(hashlib.sha256(inventory).hexdigest()))
    logical_freeze = tmp_path / "bench-balanced.val.logical.jsonl"
    verified: Any = SimpleNamespace(split=object(), provenance=object())
    observed: list[tuple[Path, Path]] = []

    def load_with_freeze(_root: Path, *, logical_freeze_path: Path) -> Any:
        observed.append((_root, logical_freeze_path))
        return verified

    monkeypatch.setattr(corpus, "_load_inventory_verified_safety_corpus", load_with_freeze)

    assert (
        load_verified_safety_corpus(
            root,
            pin_path=pin,
            logical_freeze_path=logical_freeze,
        )
        is verified
    )
    assert observed == [(root, logical_freeze)]


def test_public_loader_rejects_inventory_not_bound_by_external_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import data.safety_corpus as corpus

    root = tmp_path / "bench-balanced-val"
    root.mkdir()
    (root / "SHA256SUMS").write_bytes(b"changed inventory\n")
    pin = tmp_path / "bench-balanced-val.SHA256SUMS.sha256"
    pin.write_bytes(inventory_pin_bytes(hashlib.sha256(b"expected inventory\n").hexdigest()))
    called = False

    def unpinned_loader(_root: Path, *, logical_freeze_path: Path) -> object:
        nonlocal called
        del logical_freeze_path
        called = True
        return object()

    monkeypatch.setattr(corpus, "_load_inventory_verified_safety_corpus", unpinned_loader)

    with pytest.raises(TierCContractError, match="differs from its external pin"):
        load_verified_safety_corpus(root, pin_path=pin)
    assert not called


def test_inventory_loader_rejects_a_different_logical_freeze_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import data.safety_corpus as corpus

    root = tmp_path / "bench-balanced-val"
    root.mkdir()
    entries = tuple(
        SimpleNamespace(
            image=f"pngs/tc-{index:06d}.png",
            gt=f"gt/tc-{index:06d}.json",
        )
        for index in range(SAFETY_COUNT)
    )
    verified = SimpleNamespace(
        entries=entries,
        manifest_sha256="b" * 64,
        meta=SimpleNamespace(
            git_commit="a" * 40,
            version=DATASET_VERSION,
            manifest_schema=MANIFEST_SCHEMA,
        ),
    )
    monkeypatch.setattr(corpus, "_read_strict_json", lambda _path: _provenance())
    monkeypatch.setattr(corpus, "parse_manifest", lambda *_args, **_kwargs: entries)
    monkeypatch.setattr(corpus, "_parse_inventory", lambda _path: {})
    monkeypatch.setattr(corpus, "_expected_members", lambda _entries: set())
    monkeypatch.setattr(corpus, "load_verified_generated_split", lambda *_args: verified)
    monkeypatch.setattr(corpus, "verify_logical_freeze", lambda *_args, **_kwargs: "f" * 64)

    with pytest.raises(TierCContractError, match="provenance does not match"):
        corpus._load_inventory_verified_safety_corpus(
            root,
            logical_freeze_path=tmp_path / "logical.jsonl",
        )


def test_missing_committed_corpus_reports_the_external_checkpoint(tmp_path: Path) -> None:
    missing = tmp_path / "not-imported"

    with pytest.raises(TierCContractError, match="manual build-safety-corpus workflow"):
        load_verified_safety_corpus(missing)
