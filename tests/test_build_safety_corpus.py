"""Canonical Ubuntu builder tests without generating release bytes on Windows."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from data.generators.occurrences import DEFAULT_HELDOUT_SEED, HELDOUT_FRACTION
from data.generators.tier_c import (
    DATASET_VERSION,
    DEFAULT_SPLIT_SEED,
    MANIFEST_SCHEMA,
)
from data.safety_corpus import (
    CORPUS_SCHEMA,
    EXPECTED_PYTHON,
    EXPECTED_TESSERACT_PACKAGE,
    EXPECTED_TESSERACT_POR_PACKAGE,
    EXPECTED_UBUNTU,
    EXPECTED_UV,
    RELEASE_LINE,
    SAFETY_COUNT,
    SAFETY_DATASET,
    SAFETY_SPLIT,
    SafetyCorpusProvenance,
)
from data.tier_c_contract import (
    TierCContractError,
    TierCManifestEntry,
    TierCManifestMetaV2,
    VerifiedCanonicalSplit,
    canonical_manifest_bytes,
)
from scripts import build_safety_corpus as builder


def _provenance(manifest_sha256: str) -> SafetyCorpusProvenance:
    commit = "a" * 40
    return SafetyCorpusProvenance.model_validate(
        {
            "corpus_schema": CORPUS_SCHEMA,
            "release_line": RELEASE_LINE,
            "dataset": SAFETY_DATASET,
            "split": SAFETY_SPLIT,
            "count": SAFETY_COUNT,
            "dataset_version": DATASET_VERSION,
            "manifest_schema": MANIFEST_SCHEMA,
            "manifest_sha256": manifest_sha256,
            "generator_commit": commit,
            "generated_meta_commit": commit,
            "created_at_utc": "20260821T120000Z",
            "python_version": EXPECTED_PYTHON,
            "uv_version": EXPECTED_UV,
            "pillow_version": "12.2.0",
            "uv_lock_sha256": "b" * 64,
            "ubuntu_id": "ubuntu",
            "ubuntu_version": EXPECTED_UBUNTU,
            "runner_image": "ubuntu24",
            "runner_image_version": "20260817.1",
            "tesseract_package_version": EXPECTED_TESSERACT_PACKAGE,
            "tesseract_por_package_version": EXPECTED_TESSERACT_POR_PACKAGE,
            "tesseract_engine_version": "5.3.4",
            "tesseract_language": "por",
            "github_repository": "JoaoMiltzarek/security-shift-intake",
            "github_workflow_ref": "repo/.github/workflows/build-safety-corpus.yml@main",
            "github_sha": commit,
            "github_run_id": "123",
            "github_run_attempt": "1",
            "font_files": [{"path": "assets/fonts/Fake.ttf", "sha256": "c" * 64}],
        }
    )


def _verified_source(root: Path) -> VerifiedCanonicalSplit:
    (root / "pngs").mkdir(parents=True)
    (root / "gt").mkdir()
    entries: list[TierCManifestEntry] = []
    sheets: list[dict[str, object]] = []
    for index in range(SAFETY_COUNT):
        doc_id = f"tc-{index:06d}"
        image = f"pngs/{doc_id}.png"
        gt = f"gt/{doc_id}.json"
        image_bytes = f"png-{index}".encode()
        gt_bytes = f'{{"document_id":"{doc_id}"}}\n'.encode()
        (root / image).write_bytes(image_bytes)
        (root / gt).write_bytes(gt_bytes)
        entries.append(
            TierCManifestEntry(
                doc_id=doc_id,
                split="val",
                image=image,
                gt=gt,
                sha256_img=hashlib.sha256(image_bytes).hexdigest(),
                sha256_gt=hashlib.sha256(gt_bytes).hexdigest(),
            )
        )
        sheets.append({"document_id": doc_id})
    meta = TierCManifestMetaV2(
        manifest_schema=MANIFEST_SCHEMA,
        version=DATASET_VERSION,
        dataset=SAFETY_DATASET,
        seed=43,
        split_seed=DEFAULT_SPLIT_SEED,
        n=300,
        profile="balanced",
        counts={"train": 210, "val": 45, "test": 45},
        heldout_vocab_seed=DEFAULT_HELDOUT_SEED,
        heldout_fractions={
            "vocab": HELDOUT_FRACTION,
            "frases": HELDOUT_FRACTION,
            "variant_c_rate_test": 0.25,
            "band_cut": 0.8,
        },
        heldout_bands={"train": "lower80", "val": "lower80", "test": "upper20"},
        git_commit="a" * 40,
    )
    manifest = canonical_manifest_bytes(entries)
    return VerifiedCanonicalSplit(
        entries=tuple(entries),
        sheets=tuple(sheets),
        manifest_sha256=hashlib.sha256(manifest).hexdigest(),
        meta=meta,
    )


def test_builder_refuses_noncanonical_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builder, "_os_release", lambda: {"ID": "windows", "VERSION_ID": "11"})
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    with pytest.raises(TierCContractError, match="manual Ubuntu 24.04"):
        builder.require_canonical_builder_environment()


def test_publish_corpus_copies_exactly_45_sheets_and_replaces_stale_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generated = tmp_path / "generated"
    verified = _verified_source(generated)
    output = tmp_path / "artifact"
    output.mkdir()
    (output / "stale.txt").write_text("stale", encoding="utf-8")
    inspected: list[Path] = []

    def accept_staged(root: Path) -> object:
        inspected.append(root)
        assert len(list((root / "pngs").glob("*.png"))) == SAFETY_COUNT
        assert len(list((root / "gt").glob("*.json"))) == SAFETY_COUNT
        assert len((root / "SHA256SUMS").read_text(encoding="utf-8").splitlines()) == 93
        return object()

    monkeypatch.setattr(builder, "load_verified_safety_corpus", accept_staged)

    builder.publish_corpus(
        generated,
        output,
        verified,
        _provenance(verified.manifest_sha256),
    )

    assert inspected
    assert not (output / "stale.txt").exists()
    assert len(list((output / "pngs").glob("*.png"))) == SAFETY_COUNT
    assert (output / "provenance.json").is_file()
    assert (output / "SHA256SUMS").is_file()
    assert not list(tmp_path.glob(".artifact.staging-*"))
