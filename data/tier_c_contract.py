"""Strict, portable contract for canonical Tier C evaluation datasets.

Manifest schema v2 deliberately points the evaluator at the deterministic PNG
page, not at the derived PDF.  Every path stored in a manifest is relative to
the dataset root; frozen manifests can therefore be compared across machines
and checkout locations.

This module is read-only with respect to frozen manifests.  Creating a new
frozen manifest is an explicit release operation, never a side effect of an
evaluation run.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from data.generators.degrade import _BAND_CUT
from data.generators.occurrences import DEFAULT_HELDOUT_SEED, HELDOUT_FRACTION, Profile, Split
from data.generators.tier_c import (
    _P_VARIANT_C_TEST,
    CANONICAL_DATASETS,
    DATASET_VERSION,
    DEFAULT_SPLIT_SEED,
    MANIFEST_SCHEMA,
)
from src.paths import REPO_ROOT

V2_FROZEN_ROOT = REPO_ROOT / "data" / "manifests" / "tier_c_manifest_v2"

_DOC_ID_RE = re.compile(r"tc-\d{6}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_GIT_COMMIT_RE = re.compile(r"(?:unknown|[0-9a-f]{7,40})\Z")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_EXPECTED_BANDS = {"train": "lower80", "val": "lower80", "test": "upper20"}
_EXPECTED_FRACTIONS = {
    "vocab": HELDOUT_FRACTION,
    "frases": HELDOUT_FRACTION,
    "variant_c_rate_test": _P_VARIANT_C_TEST,
    "band_cut": _BAND_CUT,
}

# Smoke/stress are disposable development datasets.  The two benchmark priors
# freeze both the tuning split and the one-shot test split under new v2 names;
# the historical v1 JSONL files remain untouched.
_DEFAULT_FROZEN_SPLITS = frozenset(
    (dataset, split)
    for dataset in ("bench-balanced", "bench-operational")
    for split in ("val", "test")
)


class TierCContractError(RuntimeError):
    """A canonical dataset is absent, malformed, or different from its freeze."""


def _strict_json_object(text: str) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    payload = json.loads(text, object_pairs_hook=reject_duplicate_keys)
    if not isinstance(payload, dict):
        raise ValueError("JSON value must be an object")
    return payload


def _portable_member(value: str) -> PurePosixPath:
    if not value or "\\" in value or ":" in value:
        raise ValueError("path must be a portable relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value:
        raise ValueError("path must be a portable relative POSIX path")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("path must not contain empty, dot, or parent segments")
    return path


class TierCManifestEntry(BaseModel):
    """One authenticated PNG + ground-truth pair in manifest schema v2."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    doc_id: str
    split: Split
    image: str
    gt: str
    sha256_img: str
    sha256_gt: str

    @field_validator("doc_id")
    @classmethod
    def _valid_doc_id(cls, value: str) -> str:
        if _DOC_ID_RE.fullmatch(value) is None:
            raise ValueError("doc_id must match tc-NNNNNN")
        return value

    @field_validator("sha256_img", "sha256_gt")
    @classmethod
    def _valid_sha256(cls, value: str) -> str:
        if _SHA256_RE.fullmatch(value) is None:
            raise ValueError("sha256 must contain 64 lowercase hexadecimal characters")
        return value

    @model_validator(mode="after")
    def _canonical_paths(self) -> TierCManifestEntry:
        image = _portable_member(self.image)
        gt = _portable_member(self.gt)
        if image != PurePosixPath("pngs", f"{self.doc_id}.png"):
            raise ValueError("image must be exactly pngs/{doc_id}.png")
        if gt != PurePosixPath("gt", f"{self.doc_id}.json"):
            raise ValueError("gt must be exactly gt/{doc_id}.json")
        return self


class TierCManifestMetaV2(BaseModel):
    """Strict metadata authenticated before a canonical split can be evaluated."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    manifest_schema: Literal["tier_c-manifest/v2"]
    version: str
    dataset: str
    seed: int
    split_seed: int
    n: int
    profile: Profile
    counts: dict[Split, int]
    heldout_vocab_seed: int
    heldout_fractions: dict[str, float]
    heldout_bands: dict[Split, Literal["lower80", "upper20"]]
    git_commit: str

    @field_validator("counts")
    @classmethod
    def _nonnegative_counts(cls, value: dict[Split, int]) -> dict[Split, int]:
        if any(count < 0 for count in value.values()):
            raise ValueError("split counts must be non-negative")
        return value

    @field_validator("git_commit")
    @classmethod
    def _valid_git_commit(cls, value: str) -> str:
        if _GIT_COMMIT_RE.fullmatch(value) is None:
            raise ValueError("git_commit must be unknown or a 7-40 character lowercase hex id")
        return value


class VerifiedCanonicalSplit(NamedTuple):
    """Authenticated inputs ready for an evaluation loop."""

    entries: tuple[TierCManifestEntry, ...]
    sheets: tuple[dict[str, Any], ...]
    manifest_sha256: str
    meta: TierCManifestMetaV2


def canonical_gt_bytes(sheet: dict[str, Any]) -> bytes:
    """Serialize hash-relevant GT, excluding its replaceable storage pointer."""
    slim = {key: value for key, value in sheet.items() if key != "source_file"}
    return json.dumps(slim, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def sha256_file(path: Path) -> str:
    """Hash a file without loading an evaluation image into one large buffer."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_manifest_bytes(entries: Sequence[TierCManifestEntry]) -> bytes:
    """Return order-independent canonical JSONL bytes for freeze comparison."""
    ordered = sorted(entries, key=lambda entry: entry.doc_id)
    lines = [
        json.dumps(
            entry.model_dump(mode="json"),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        for entry in ordered
    ]
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")


def parse_manifest(
    path: Path, *, expected_split: Split | None = None
) -> tuple[TierCManifestEntry, ...]:
    """Parse a strict v2 JSONL manifest and reject duplicate identities or paths."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise TierCContractError(f"cannot read Tier C manifest: {path}") from exc
    if not text or not text.strip():
        raise TierCContractError(f"Tier C manifest is empty: {path}")

    entries: list[TierCManifestEntry] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise TierCContractError(f"blank line in Tier C manifest at line {line_number}")
        try:
            payload = _strict_json_object(line)
            entry = TierCManifestEntry.model_validate(payload)
        except (ValidationError, ValueError) as exc:
            raise TierCContractError(
                f"invalid Tier C manifest entry at line {line_number}"
            ) from exc
        if expected_split is not None and entry.split != expected_split:
            raise TierCContractError(
                f"manifest entry {entry.doc_id} belongs to {entry.split}, expected {expected_split}"
            )
        entries.append(entry)

    for label, values in (
        ("doc_id", [entry.doc_id for entry in entries]),
        ("image", [entry.image for entry in entries]),
        ("gt", [entry.gt for entry in entries]),
    ):
        if len(values) != len(set(values)):
            raise TierCContractError(f"duplicate {label} in Tier C manifest")
    return tuple(entries)


def resolve_dataset_member(root: Path, portable_path: str) -> Path:
    """Resolve one manifest member under *root*, including roots with spaces."""
    member = _portable_member(portable_path)
    try:
        root_resolved = root.resolve(strict=True)
    except OSError as exc:
        raise TierCContractError(f"Tier C dataset root is unavailable: {root}") from exc
    candidate = root_resolved.joinpath(*member.parts).resolve(strict=False)
    if not candidate.is_relative_to(root_resolved):
        raise TierCContractError("Tier C manifest member escapes the dataset root")
    return candidate


def default_frozen_manifest_path(dataset: str, split: Split) -> Path | None:
    """Return the repository-anchored v2 freeze, if this split must be frozen."""
    if (dataset, split) not in _DEFAULT_FROZEN_SPLITS:
        return None
    return V2_FROZEN_ROOT / f"{dataset}.{split}.jsonl"


def _load_verified_meta(root: Path, dataset: str) -> TierCManifestMetaV2:
    meta_path = root / "meta.json"
    try:
        payload = _strict_json_object(meta_path.read_text(encoding="utf-8"))
        meta = TierCManifestMetaV2.model_validate(payload)
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        raise TierCContractError(f"invalid Tier C v2 metadata: {meta_path}") from exc

    try:
        spec = CANONICAL_DATASETS[dataset]
    except KeyError as exc:
        raise TierCContractError(f"unknown canonical Tier C dataset: {dataset}") from exc

    expected_counts: dict[str, int] = {
        "train": int(spec.n * 0.70),
        "val": int(spec.n * 0.15),
    }
    expected_counts["test"] = spec.n - expected_counts["train"] - expected_counts["val"]
    expected = {
        "manifest_schema": MANIFEST_SCHEMA,
        "version": DATASET_VERSION,
        "dataset": dataset,
        "seed": spec.seed,
        "split_seed": DEFAULT_SPLIT_SEED,
        "n": spec.n,
        "profile": spec.profile,
        "counts": expected_counts,
        "heldout_vocab_seed": DEFAULT_HELDOUT_SEED,
        "heldout_fractions": _EXPECTED_FRACTIONS,
        "heldout_bands": _EXPECTED_BANDS,
    }
    observed = meta.model_dump(mode="python")
    for key, expected_value in expected.items():
        if observed[key] != expected_value:
            raise TierCContractError(f"Tier C metadata does not match canonical {dataset}: {key}")
    return meta


def _validate_ground_truth(
    sheet: dict[str, Any], entry: TierCManifestEntry, meta: TierCManifestMetaV2
) -> None:
    required = {
        "schema_version": "1.0",
        "document_id": entry.doc_id,
        "review_status": "synthetic_ground_truth",
        "truth_source": "generator",
    }
    for key, expected in required.items():
        if sheet.get(key) != expected:
            raise TierCContractError(f"ground truth invariant failed for {entry.doc_id}: {key}")
    if not isinstance(sheet.get("cabecalho"), dict):
        raise TierCContractError(f"ground truth invariant failed for {entry.doc_id}: cabecalho")
    if type(sheet.get("sem_alteracao")) is not bool or type(sheet.get("riscado")) is not bool:
        raise TierCContractError(f"ground truth invariant failed for {entry.doc_id}: disposition")
    occurrences = sheet.get("ocorrencias")
    if not isinstance(occurrences, list):
        raise TierCContractError(f"ground truth invariant failed for {entry.doc_id}: ocorrencias")
    if sheet["sem_alteracao"] and occurrences:
        raise TierCContractError(
            f"ground truth invariant failed for {entry.doc_id}: sem_alteracao with occurrences"
        )
    synthetic = sheet.get("synthetic")
    expected_synthetic = {
        "generator": meta.version,
        "dataset": meta.dataset,
        "seed": meta.seed,
        "split": entry.split,
        "profile": meta.profile,
    }
    if not isinstance(synthetic, dict) or any(
        synthetic.get(key) != expected for key, expected in expected_synthetic.items()
    ):
        raise TierCContractError(
            f"ground truth invariant failed for {entry.doc_id}: synthetic provenance"
        )


def _verify_entry(
    root: Path, entry: TierCManifestEntry, meta: TierCManifestMetaV2
) -> dict[str, Any]:
    image_path = resolve_dataset_member(root, entry.image)
    gt_path = resolve_dataset_member(root, entry.gt)
    try:
        if not image_path.is_file() or not gt_path.is_file():
            raise TierCContractError(f"Tier C files are missing for {entry.doc_id}")
        with image_path.open("rb") as image_handle:
            if image_handle.read(len(_PNG_SIGNATURE)) != _PNG_SIGNATURE:
                raise TierCContractError(f"Tier C image is not PNG for {entry.doc_id}")
        if sha256_file(image_path) != entry.sha256_img:
            raise TierCContractError(f"Tier C PNG hash mismatch for {entry.doc_id}")
        sheet = _strict_json_object(gt_path.read_text(encoding="utf-8"))
    except TierCContractError:
        raise
    except (OSError, UnicodeError, ValueError) as exc:
        raise TierCContractError(f"cannot verify Tier C files for {entry.doc_id}") from exc
    if hashlib.sha256(canonical_gt_bytes(sheet)).hexdigest() != entry.sha256_gt:
        raise TierCContractError(f"Tier C ground-truth hash mismatch for {entry.doc_id}")
    _validate_ground_truth(sheet, entry, meta)

    verified_sheet = dict(sheet)
    verified_sheet["source_file"] = str(image_path)
    return verified_sheet


def load_verified_canonical_split(
    root: Path,
    dataset: str,
    split: Split,
    *,
    frozen_path: Path | None = None,
) -> VerifiedCanonicalSplit:
    """Authenticate one canonical split and return only verified PNG-backed sheets.

    If a canonical benchmark split has a default freeze, its absence is a hard
    failure.  Passing an explicit path is useful for release tooling and tests;
    this function never creates or updates that file.
    """
    root_resolved = root.resolve(strict=False)
    meta = _load_verified_meta(root_resolved, dataset)
    manifest_path = root_resolved / "manifests" / f"{split}.jsonl"
    entries = parse_manifest(manifest_path, expected_split=split)
    expected_count = meta.counts[split]
    if len(entries) != expected_count:
        raise TierCContractError(
            f"Tier C {split} count mismatch: manifest={len(entries)}, meta={expected_count}"
        )

    freeze = (
        frozen_path if frozen_path is not None else default_frozen_manifest_path(dataset, split)
    )
    if freeze is not None:
        if not freeze.is_absolute():
            freeze = REPO_ROOT / freeze
        frozen_entries = parse_manifest(freeze, expected_split=split)
        if canonical_manifest_bytes(entries) != canonical_manifest_bytes(frozen_entries):
            raise TierCContractError(f"Tier C manifest differs from its read-only freeze: {freeze}")

    sheets = tuple(_verify_entry(root_resolved, entry, meta) for entry in entries)
    canonical = canonical_manifest_bytes(entries)
    return VerifiedCanonicalSplit(
        entries=entries,
        sheets=sheets,
        manifest_sha256=hashlib.sha256(canonical).hexdigest(),
        meta=meta,
    )
