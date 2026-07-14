"""Release-contract tests for portable, authenticated Tier C manifests."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from data.generators.tier_c import CANONICAL_DATASETS, DATASET_VERSION
from data.tier_c_contract import (
    MANIFEST_SCHEMA,
    V2_FROZEN_ROOT,
    TierCContractError,
    TierCManifestEntry,
    canonical_gt_bytes,
    canonical_manifest_bytes,
    default_frozen_manifest_path,
    load_verified_canonical_split,
    parse_manifest,
    resolve_dataset_member,
)
from src.paths import REPO_ROOT

_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _sheet(doc_id: str, split: str = "val") -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "document_id": doc_id,
        # Deliberately non-portable/stale: the verified loader replaces this in memory.
        "source_file": "old-machine/derived.pdf",
        "review_status": "synthetic_ground_truth",
        "truth_source": "generator",
        "cabecalho": {
            "data": "01/01/2031 - Dia",
            "turno": "Dia",
            "vigilantes": ["Pessoa Sintetica"],
            "unidade": "Posto Delta",
        },
        "sem_alteracao": True,
        "riscado": False,
        "ocorrencias": [],
        "synthetic": {
            "generator": DATASET_VERSION,
            "dataset": "smoke",
            "seed": 42,
            "split": split,
            "template": "controle_A",
            "profile": "balanced",
            "difficulty": "clean",
        },
    }


def _meta() -> dict[str, object]:
    return {
        "manifest_schema": MANIFEST_SCHEMA,
        "version": DATASET_VERSION,
        "dataset": "smoke",
        "seed": 42,
        "split_seed": 0,
        "n": 50,
        "profile": "balanced",
        "counts": {"train": 35, "val": 7, "test": 8},
        "heldout_vocab_seed": 7,
        "heldout_fractions": {
            "vocab": 0.2,
            "frases": 0.2,
            "variant_c_rate_test": 0.25,
            "band_cut": 0.8,
        },
        "heldout_bands": {"train": "lower80", "val": "lower80", "test": "upper20"},
        "git_commit": "abcdef0",
    }


def _dataset(root: Path) -> tuple[list[TierCManifestEntry], Path]:
    (root / "pngs").mkdir(parents=True)
    (root / "gt").mkdir()
    (root / "manifests").mkdir()
    (root / "meta.json").write_text(json.dumps(_meta()), encoding="utf-8")

    entries: list[TierCManifestEntry] = []
    for index in range(7):
        doc_id = f"tc-{index:06d}"
        image_path = root / "pngs" / f"{doc_id}.png"
        image_path.write_bytes(_PNG_1X1)
        sheet = _sheet(doc_id)
        gt_path = root / "gt" / f"{doc_id}.json"
        gt_path.write_text(json.dumps(sheet, ensure_ascii=False, indent=2), encoding="utf-8")
        entries.append(
            TierCManifestEntry(
                doc_id=doc_id,
                split="val",
                image=f"pngs/{doc_id}.png",
                gt=f"gt/{doc_id}.json",
                sha256_img=hashlib.sha256(_PNG_1X1).hexdigest(),
                sha256_gt=hashlib.sha256(canonical_gt_bytes(sheet)).hexdigest(),
            )
        )

    local = root / "manifests" / "val.jsonl"
    local.write_bytes(canonical_manifest_bytes(entries))
    frozen = root.parent / "read only freeze.jsonl"
    # Different row order is semantically equal under canonical comparison.
    frozen.write_bytes(b"\n".join(reversed(local.read_bytes().splitlines())) + b"\n")
    return entries, frozen


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("doc_id", "tc-1"),
        ("image", "pdfs/tc-000001.pdf"),
        ("image", "../pngs/tc-000001.png"),
        ("image", r"pngs\tc-000001.png"),
        ("image", "C:/pngs/tc-000001.png"),
        ("gt", "gt/other.json"),
        ("sha256_img", "A" * 64),
        ("sha256_gt", "0" * 63),
    ],
)
def test_entry_rejects_noncanonical_identity_path_or_hash(field: str, value: str) -> None:
    payload: dict[str, object] = {
        "doc_id": "tc-000001",
        "split": "test",
        "image": "pngs/tc-000001.png",
        "gt": "gt/tc-000001.json",
        "sha256_img": "0" * 64,
        "sha256_gt": "1" * 64,
    }
    payload[field] = value
    with pytest.raises(ValidationError):
        TierCManifestEntry.model_validate(payload)


def test_entry_forbids_unknown_fields_and_coercion() -> None:
    payload: dict[str, object] = {
        "doc_id": "tc-000001",
        "split": "test",
        "image": "pngs/tc-000001.png",
        "gt": "gt/tc-000001.json",
        "sha256_img": "0" * 64,
        "sha256_gt": "1" * 64,
        "pdf": "derived.pdf",
    }
    with pytest.raises(ValidationError):
        TierCManifestEntry.model_validate(payload)
    payload.pop("pdf")
    payload["doc_id"] = 1
    with pytest.raises(ValidationError):
        TierCManifestEntry.model_validate(payload)


def test_manifest_parser_rejects_duplicates_and_wrong_split(tmp_path: Path) -> None:
    entry = TierCManifestEntry(
        doc_id="tc-000001",
        split="test",
        image="pngs/tc-000001.png",
        gt="gt/tc-000001.json",
        sha256_img="0" * 64,
        sha256_gt="1" * 64,
    )
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_bytes(canonical_manifest_bytes([entry, entry]))
    with pytest.raises(TierCContractError, match="duplicate doc_id"):
        parse_manifest(manifest, expected_split="test")
    manifest.write_bytes(canonical_manifest_bytes([entry]))
    with pytest.raises(TierCContractError, match="expected val"):
        parse_manifest(manifest, expected_split="val")


def test_manifest_parser_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        '{"doc_id":"tc-000001","doc_id":"tc-000002","split":"test",'
        '"image":"pngs/tc-000002.png","gt":"gt/tc-000002.json",'
        f'"sha256_img":"{"0" * 64}","sha256_gt":"{"1" * 64}"}}\n',
        encoding="utf-8",
    )
    with pytest.raises(TierCContractError, match="invalid Tier C manifest entry"):
        parse_manifest(manifest, expected_split="test")


def test_resolve_dataset_member_supports_spaces_and_blocks_escape(tmp_path: Path) -> None:
    root = tmp_path / "canonical dataset with spaces"
    (root / "pngs").mkdir(parents=True)
    assert (
        resolve_dataset_member(root, "pngs/tc-000001.png")
        == (root / "pngs" / "tc-000001.png").resolve()
    )
    with pytest.raises(ValueError, match="parent"):
        resolve_dataset_member(root, "../outside.png")


def test_load_verified_split_authenticates_files_and_replaces_source_path(tmp_path: Path) -> None:
    root = tmp_path / "canonical dataset with spaces"
    entries, frozen = _dataset(root)

    verified = load_verified_canonical_split(root, "smoke", "val", frozen_path=frozen)

    assert verified.entries == tuple(entries)
    assert verified.manifest_sha256 == hashlib.sha256(canonical_manifest_bytes(entries)).hexdigest()
    assert len(verified.sheets) == 7
    assert all(Path(str(sheet["source_file"])).is_file() for sheet in verified.sheets)
    assert all(Path(str(sheet["source_file"])).suffix == ".png" for sheet in verified.sheets)
    assert "canonical dataset with spaces" in str(verified.sheets[0]["source_file"])


def test_load_verified_split_rejects_wrong_meta_count_or_bytes(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    _, frozen = _dataset(root)
    meta = _meta()
    meta["counts"] = {"train": 35, "val": 6, "test": 9}
    (root / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(TierCContractError, match="metadata.*counts"):
        load_verified_canonical_split(root, "smoke", "val", frozen_path=frozen)

    (root / "meta.json").write_text(json.dumps(_meta()), encoding="utf-8")
    (root / "pngs" / "tc-000000.png").write_bytes(_PNG_1X1 + b"tampered")
    with pytest.raises(TierCContractError, match="PNG hash mismatch"):
        load_verified_canonical_split(root, "smoke", "val", frozen_path=frozen)


def test_load_verified_split_rejects_frozen_drift_before_evaluation(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    entries, frozen = _dataset(root)
    drifted = [entries[0].model_copy(update={"sha256_img": "f" * 64}), *entries[1:]]
    frozen.write_bytes(canonical_manifest_bytes(drifted))

    with pytest.raises(TierCContractError, match="read-only freeze"):
        load_verified_canonical_split(root, "smoke", "val", frozen_path=frozen)


def test_load_verified_split_rejects_gt_provenance_even_with_matching_hash(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    entries, frozen = _dataset(root)
    gt_path = root / "gt" / "tc-000000.json"
    sheet = json.loads(gt_path.read_text(encoding="utf-8"))
    sheet["truth_source"] = "human_curation"
    gt_path.write_text(json.dumps(sheet), encoding="utf-8")
    changed = entries[0].model_copy(
        update={"sha256_gt": hashlib.sha256(canonical_gt_bytes(sheet)).hexdigest()}
    )
    changed_entries = [changed, *entries[1:]]
    (root / "manifests" / "val.jsonl").write_bytes(canonical_manifest_bytes(changed_entries))
    frozen.write_bytes(canonical_manifest_bytes(changed_entries))

    with pytest.raises(TierCContractError, match="truth_source"):
        load_verified_canonical_split(root, "smoke", "val", frozen_path=frozen)


def test_default_v2_freezes_are_repo_anchored_and_leave_v1_untouched() -> None:
    expected = V2_FROZEN_ROOT / "bench-balanced.test.jsonl"
    assert default_frozen_manifest_path("bench-balanced", "test") == expected
    assert expected.is_absolute()
    assert expected.is_relative_to(REPO_ROOT)
    assert default_frozen_manifest_path("smoke", "val") is None
    assert CANONICAL_DATASETS["bench-balanced"].frozen_manifest != str(expected)
