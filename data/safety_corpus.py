"""Authenticated contract for the committed v1.1 structural-safety corpus."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from data.generators.fonts import discover_handwriting_fonts
from data.generators.tier_c import DATASET_VERSION, MANIFEST_SCHEMA
from data.tier_c_contract import (
    SAFETY_LOGICAL_FREEZE,
    TierCContractError,
    TierCManifestEntry,
    VerifiedCanonicalSplit,
    load_verified_generated_split,
    parse_manifest,
    sha256_file,
    verify_logical_freeze,
)
from src.paths import REPO_ROOT

CORPUS_SCHEMA: Literal["ssi-safety-corpus/v1"] = "ssi-safety-corpus/v1"
RELEASE_LINE: Literal["v1.1"] = "v1.1"
SAFETY_DATASET = "bench-balanced"
SAFETY_SPLIT: Literal["val"] = "val"
SAFETY_COUNT = 45
SAFETY_CORPUS_DIR = (
    REPO_ROOT / "data" / "eval_corpora" / RELEASE_LINE / (f"{SAFETY_DATASET}-{SAFETY_SPLIT}")
)
PROVENANCE_NAME = "provenance.json"
INVENTORY_NAME = "SHA256SUMS"
SAFETY_CORPUS_PIN_RELATIVE = Path(
    "data",
    "manifests",
    "safety_corpus_v1.1",
    "bench-balanced.val.inventory.sha256",
)
SAFETY_CORPUS_PIN = REPO_ROOT / SAFETY_CORPUS_PIN_RELATIVE
INVENTORY_PIN_TARGET = (SAFETY_CORPUS_DIR / INVENTORY_NAME).relative_to(REPO_ROOT).as_posix()
EXPECTED_PYTHON = "3.11.15"
EXPECTED_UV = "0.11.28"
EXPECTED_UBUNTU = "24.04"
EXPECTED_TESSERACT_PACKAGE = "5.3.4-1build5"
EXPECTED_TESSERACT_POR_PACKAGE = "1:4.1.0-2"

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
_TIMESTAMP_RE = re.compile(r"\d{8}T\d{6}Z\Z")


class CorpusFontIdentity(BaseModel):
    """One repository-relative font identity used by the renderer."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    path: str
    sha256: str

    @field_validator("path")
    @classmethod
    def _portable_font_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or path.as_posix() != value
            or any(part in {"", ".", ".."} for part in path.parts)
            or path.suffix.lower() not in {".ttf", ".otf"}
        ):
            raise ValueError("font path must be a portable repository-relative font")
        return value

    @field_validator("sha256")
    @classmethod
    def _valid_hash(cls, value: str) -> str:
        if _SHA256_RE.fullmatch(value) is None:
            raise ValueError("font sha256 is invalid")
        return value


class SafetyCorpusProvenance(BaseModel):
    """Closed provenance schema emitted only by the canonical Ubuntu builder."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    corpus_schema: Literal["ssi-safety-corpus/v1"]
    release_line: Literal["v1.1"]
    dataset: Literal["bench-balanced"]
    split: Literal["val"]
    count: Literal[45]
    dataset_version: str
    manifest_schema: Literal["tier_c-manifest/v2"]
    manifest_sha256: str
    generator_commit: str
    generated_meta_commit: str
    created_at_utc: str
    python_version: Literal["3.11.15"]
    uv_version: Literal["0.11.28"]
    pillow_version: str
    uv_lock_sha256: str
    ubuntu_id: Literal["ubuntu"]
    ubuntu_version: Literal["24.04"]
    runner_image: str
    runner_image_version: str
    tesseract_package_version: Literal["5.3.4-1build5"]
    tesseract_por_package_version: Literal["1:4.1.0-2"]
    tesseract_engine_version: str
    tesseract_language: Literal["por"]
    github_repository: Literal["JoaoMiltzarek/security-shift-intake"]
    github_workflow_ref: str
    github_sha: str
    github_run_id: str
    github_run_attempt: str
    font_files: list[CorpusFontIdentity]

    @field_validator(
        "manifest_sha256",
        "uv_lock_sha256",
    )
    @classmethod
    def _valid_hash(cls, value: str) -> str:
        if _SHA256_RE.fullmatch(value) is None:
            raise ValueError("sha256 is invalid")
        return value

    @field_validator("generator_commit", "generated_meta_commit", "github_sha")
    @classmethod
    def _valid_commit(cls, value: str) -> str:
        if _COMMIT_RE.fullmatch(value) is None:
            raise ValueError("commit identity is invalid")
        return value

    @model_validator(mode="after")
    def _coherent_provenance(self) -> SafetyCorpusProvenance:
        if self.dataset_version != DATASET_VERSION:
            raise ValueError("dataset version does not match the active generator")
        if self.manifest_schema != MANIFEST_SCHEMA:
            raise ValueError("manifest schema does not match the active generator")
        if _TIMESTAMP_RE.fullmatch(self.created_at_utc) is None:
            raise ValueError("created_at_utc must use compact UTC format")
        if not all(
            value.strip()
            for value in (
                self.pillow_version,
                self.runner_image,
                self.runner_image_version,
                self.tesseract_engine_version,
                self.github_workflow_ref,
                self.github_run_id,
                self.github_run_attempt,
            )
        ):
            raise ValueError("provenance strings must be non-blank")
        if not (self.generator_commit == self.generated_meta_commit == self.github_sha):
            raise ValueError("generator, metadata, and workflow commits must agree")
        paths = [font.path for font in self.font_files]
        if not paths or paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("font identities must be non-empty, unique, and sorted")
        return self


class VerifiedSafetyCorpus(NamedTuple):
    """Fully authenticated safety inputs and their canonical build provenance."""

    split: VerifiedCanonicalSplit
    provenance: SafetyCorpusProvenance


def current_font_identities() -> list[CorpusFontIdentity]:
    """Return the sorted identities of every bundled handwriting font."""
    return [
        CorpusFontIdentity(
            path=path.relative_to(REPO_ROOT).as_posix(),
            sha256=sha256_file(path),
        )
        for path in discover_handwriting_fonts()
    ]


def inventory_bytes(files: dict[str, str]) -> bytes:
    """Serialize a complete path-to-hash map as deterministic sha256sum text."""
    lines: list[str] = []
    for path, digest in sorted(files.items()):
        portable = PurePosixPath(path)
        if (
            portable.is_absolute()
            or portable.as_posix() != path
            or any(part in {"", ".", ".."} for part in portable.parts)
            or _SHA256_RE.fullmatch(digest) is None
        ):
            raise ValueError("invalid corpus inventory member")
        lines.append(f"{digest}  {path}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def inventory_pin_bytes(inventory_sha256: str) -> bytes:
    """Serialize the external, reviewable pin for one corpus inventory."""
    if _SHA256_RE.fullmatch(inventory_sha256) is None:
        raise ValueError("invalid safety corpus inventory pin")
    return f"{inventory_sha256}  {INVENTORY_PIN_TARGET}\n".encode()


def parse_inventory_pin(content: bytes) -> str:
    """Parse canonical pin bytes without selecting a trust source for them."""
    try:
        line = content.decode("utf-8")
    except UnicodeError as exc:
        raise TierCContractError("external safety corpus inventory pin is invalid") from exc
    match = re.fullmatch(rf"([0-9a-f]{{64}})  {re.escape(INVENTORY_PIN_TARGET)}\n", line)
    if match is None or inventory_pin_bytes(match.group(1)) != content:
        raise TierCContractError("external safety corpus inventory pin is invalid")
    return match.group(1)


def _read_inventory_pin(path: Path) -> str:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise TierCContractError("external safety corpus inventory pin is unavailable") from exc
    return parse_inventory_pin(content)


def _read_strict_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    if not isinstance(payload, dict):
        raise ValueError("JSON value must be an object")
    return payload


def _parse_inventory(path: Path) -> dict[str, str]:
    content = path.read_bytes()
    if b"\r" in content or not content.endswith(b"\n"):
        raise TierCContractError("safety corpus inventory is not canonical LF text")
    files: dict[str, str] = {}
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise TierCContractError("safety corpus inventory is not UTF-8") from exc
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if match is None or match.group(2) in files:
            raise TierCContractError("safety corpus inventory entry is invalid")
        files[match.group(2)] = match.group(1)
    try:
        if inventory_bytes(files) != content:
            raise TierCContractError("safety corpus inventory is not canonically ordered")
    except ValueError as exc:
        raise TierCContractError("safety corpus inventory entry is invalid") from exc
    return files


def _expected_members(entries: tuple[TierCManifestEntry, ...]) -> set[str]:
    return {
        "meta.json",
        f"manifests/{SAFETY_SPLIT}.jsonl",
        PROVENANCE_NAME,
        *(entry.image for entry in entries),
        *(entry.gt for entry in entries),
    }


def _load_inventory_verified_safety_corpus(
    root: Path,
    *,
    logical_freeze_path: Path,
) -> VerifiedSafetyCorpus:
    """Validate the self-contained builder artifact before publication."""
    if not root.is_dir():
        raise TierCContractError(
            "committed v1.1 safety corpus is missing at "
            f"{root}; run the manual build-safety-corpus workflow and import its artifact"
        )
    try:
        provenance = SafetyCorpusProvenance.model_validate(
            _read_strict_json(root / PROVENANCE_NAME)
        )
        entries = parse_manifest(root / "manifests" / f"{SAFETY_SPLIT}.jsonl", expected_split="val")
        inventory = _parse_inventory(root / INVENTORY_NAME)
    except TierCContractError:
        raise
    except (OSError, UnicodeError, ValueError, ValidationError) as exc:
        raise TierCContractError("safety corpus provenance is invalid") from exc

    if len(entries) != SAFETY_COUNT:
        raise TierCContractError(
            f"safety corpus count mismatch: manifest={len(entries)}, expected={SAFETY_COUNT}"
        )
    expected = _expected_members(entries)
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != INVENTORY_NAME
    }
    if set(inventory) != expected or actual != expected:
        raise TierCContractError("safety corpus inventory does not cover exactly the corpus")
    for relative, expected_hash in inventory.items():
        if sha256_file(root.joinpath(*PurePosixPath(relative).parts)) != expected_hash:
            raise TierCContractError(f"safety corpus inventory hash mismatch: {relative}")

    verified = load_verified_generated_split(
        root,
        SAFETY_DATASET,
        SAFETY_SPLIT,
    )
    verify_logical_freeze(
        verified.entries,
        logical_freeze_path,
        expected_split=SAFETY_SPLIT,
    )
    if (
        verified.manifest_sha256 != provenance.manifest_sha256
        or verified.meta.git_commit != provenance.generated_meta_commit
        or verified.meta.version != provenance.dataset_version
        or verified.meta.manifest_schema != provenance.manifest_schema
    ):
        raise TierCContractError("safety corpus provenance does not match authenticated inputs")
    if sha256_file(REPO_ROOT / "uv.lock") != provenance.uv_lock_sha256:
        raise TierCContractError("safety corpus uv.lock identity differs from this checkout")
    if current_font_identities() != provenance.font_files:
        raise TierCContractError("safety corpus font identities differ from this checkout")
    return VerifiedSafetyCorpus(split=verified, provenance=provenance)


def load_built_safety_corpus(
    root: Path,
    *,
    logical_freeze_path: Path = SAFETY_LOGICAL_FREEZE,
) -> VerifiedSafetyCorpus:
    """Validate a fresh builder artifact before an external pin can exist."""
    return _load_inventory_verified_safety_corpus(
        root,
        logical_freeze_path=logical_freeze_path,
    )


def load_verified_safety_corpus(
    root: Path = SAFETY_CORPUS_DIR,
    *,
    pin_path: Path = SAFETY_CORPUS_PIN,
    logical_freeze_path: Path = SAFETY_LOGICAL_FREEZE,
) -> VerifiedSafetyCorpus:
    """Load the committed corpus only when its external inventory pin agrees."""
    if not root.is_dir():
        raise TierCContractError(
            "committed v1.1 safety corpus is missing at "
            f"{root}; run the manual build-safety-corpus workflow and import its artifact"
        )
    pinned_inventory = _read_inventory_pin(pin_path)
    inventory_path = root / INVENTORY_NAME
    try:
        observed_inventory = sha256_file(inventory_path)
    except OSError as exc:
        raise TierCContractError("safety corpus inventory is unavailable") from exc
    if observed_inventory != pinned_inventory:
        raise TierCContractError("safety corpus inventory differs from its external pin")
    return _load_inventory_verified_safety_corpus(
        root,
        logical_freeze_path=logical_freeze_path,
    )
