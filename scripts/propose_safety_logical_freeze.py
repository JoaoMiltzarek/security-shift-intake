"""Emit an explicitly untrusted logical-freeze candidate on canonical Ubuntu."""

from __future__ import annotations

import argparse
import importlib.metadata
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from data.canonical_io import canonical_json_bytes
from data.generators.tier_c import (
    DATASET_VERSION,
    MANIFEST_SCHEMA,
    _publish_fresh_tree,
    build_tier_c,
)
from data.safety_corpus import (
    EXPECTED_PYTHON,
    EXPECTED_UV,
    SAFETY_COUNT,
    SAFETY_DATASET,
    SAFETY_SPLIT,
    CorpusFontIdentity,
    current_font_identities,
    uv_release_version,
)
from data.tier_c_contract import (
    TierCContractError,
    VerifiedCanonicalSplit,
    canonical_logical_freeze_bytes,
    default_logical_freeze_path,
    load_verified_generated_split,
    logical_freeze_projection,
    logical_freeze_sha256,
    sha256_file,
)
from scripts.build_safety_corpus import require_canonical_builder_environment
from src.paths import REPO_ROOT

CANDIDATE_SCHEMA = "ssi-logical-freeze-candidate/v1"
CANDIDATE_STATUS = "UNTRUSTED_NOT_RELEASE_EVIDENCE"
PROVENANCE_NAME = "candidate-provenance.json"
EXPECTED_REPOSITORY = "JoaoMiltzarek/security-shift-intake"
PROPOSAL_WORKFLOW_PATH = ".github/workflows/propose-safety-logical-freeze.yml"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")


class CandidateProvenance(BaseModel):
    """Closed identity schema for an explicitly untrusted freeze proposal."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    candidate_schema: Literal["ssi-logical-freeze-candidate/v1"]
    status: Literal["UNTRUSTED_NOT_RELEASE_EVIDENCE"]
    dataset: Literal["bench-balanced"]
    split: Literal["val"]
    count: Literal[45]
    dataset_version: str
    manifest_schema: Literal["tier_c-manifest/v2"]
    logical_freeze_sha256: str
    first_manifest_sha256: str
    second_manifest_sha256: str
    generator_commit: str
    github_sha: str
    github_repository: Literal["JoaoMiltzarek/security-shift-intake"]
    github_event_name: Literal["workflow_dispatch"]
    github_ref: str
    github_workflow_ref: str
    github_run_id: str
    github_run_attempt: str
    python_version: Literal["3.11.15"]
    uv_version: Literal["0.11.28"]
    pillow_version: str
    uv_lock_sha256: str
    ubuntu_id: Literal["ubuntu"]
    ubuntu_version: Literal["24.04"]
    runner_image: str
    runner_image_version: str
    font_files: list[CorpusFontIdentity]

    @field_validator(
        "logical_freeze_sha256",
        "first_manifest_sha256",
        "second_manifest_sha256",
        "uv_lock_sha256",
    )
    @classmethod
    def _valid_hash(cls, value: str) -> str:
        if _SHA256_RE.fullmatch(value) is None:
            raise ValueError("candidate sha256 is invalid")
        return value

    @field_validator("generator_commit", "github_sha")
    @classmethod
    def _valid_commit(cls, value: str) -> str:
        if _COMMIT_RE.fullmatch(value) is None:
            raise ValueError("candidate commit identity is invalid")
        return value

    @model_validator(mode="after")
    def _coherent_candidate(self) -> CandidateProvenance:
        if self.dataset_version != DATASET_VERSION:
            raise ValueError("candidate dataset version is not active")
        if self.manifest_schema != MANIFEST_SCHEMA:
            raise ValueError("candidate manifest schema is not active")
        if self.generator_commit != self.github_sha:
            raise ValueError("candidate commit identities differ")
        expected_workflow = f"{EXPECTED_REPOSITORY}/{PROPOSAL_WORKFLOW_PATH}@{self.github_ref}"
        if not self.github_ref.strip() or self.github_workflow_ref != expected_workflow:
            raise ValueError("candidate workflow identity is incoherent")
        strings = (
            self.github_run_id,
            self.github_run_attempt,
            self.pillow_version,
            self.runner_image,
            self.runner_image_version,
        )
        if not all(value.strip() for value in strings):
            raise ValueError("candidate provenance strings must be non-blank")
        paths = [font.path for font in self.font_files]
        if not paths or paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("candidate font identities must be non-empty, unique, and sorted")
        return self


@dataclass(frozen=True)
class CandidateRuntimeAttestation:
    """Runtime identities carried beside an explicitly untrusted candidate."""

    uv_version: str
    pillow_version: str
    uv_lock_sha256: str
    ubuntu_id: str
    ubuntu_version: str
    runner_image: str
    runner_image_version: str
    font_files: tuple[CorpusFontIdentity, ...]

    def provenance_fields(self) -> dict[str, object]:
        return {
            "uv_version": self.uv_version,
            "pillow_version": self.pillow_version,
            "uv_lock_sha256": self.uv_lock_sha256,
            "ubuntu_id": self.ubuntu_id,
            "ubuntu_version": self.ubuntu_version,
            "runner_image": self.runner_image,
            "runner_image_version": self.runner_image_version,
            "font_files": [font.model_dump(mode="json") for font in self.font_files],
        }


def _command_output(args: list[str]) -> str:
    try:
        completed = subprocess.run(
            args,
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise TierCContractError(f"candidate attestation command failed: {args[0]}") from exc
    return completed.stdout.strip()


def _git_commit() -> str:
    try:
        return _command_output(["git", "rev-parse", "HEAD"])
    except TierCContractError as exc:
        raise TierCContractError("cannot identify the logical-freeze candidate commit") from exc


def require_proposal_environment() -> dict[str, str]:
    """Require the exact manual workflow before an untrusted proposal can run."""
    release = require_canonical_builder_environment()
    event_name = os.environ.get("GITHUB_EVENT_NAME")
    github_ref = os.environ.get("GITHUB_REF")
    workflow_ref = os.environ.get("GITHUB_WORKFLOW_REF")
    if event_name != "workflow_dispatch":
        raise TierCContractError("logical-freeze proposals require workflow_dispatch")
    if not github_ref:
        raise TierCContractError("logical-freeze proposal ref is unavailable")
    expected_workflow_ref = f"{EXPECTED_REPOSITORY}/{PROPOSAL_WORKFLOW_PATH}@{github_ref}"
    if workflow_ref != expected_workflow_ref:
        raise TierCContractError("logical-freeze proposal workflow identity is invalid")
    return release


def _environment(name: str) -> str:
    return os.environ[name].strip()


def collect_candidate_runtime(release: dict[str, str]) -> CandidateRuntimeAttestation:
    """Collect identities that can affect a logical-freeze proposal."""
    uv_output = _command_output(["uv", "--version"])
    if uv_release_version(uv_output) != EXPECTED_UV:
        raise TierCContractError(f"logical-freeze candidate requires uv {EXPECTED_UV}")
    try:
        pillow_version = importlib.metadata.version("pillow")
    except importlib.metadata.PackageNotFoundError as exc:
        raise TierCContractError("logical-freeze candidate requires Pillow") from exc
    runner_image = _environment("ImageOS")
    runner_image_version = _environment("ImageVersion")
    ubuntu_id = release.get("ID", "").strip()
    ubuntu_version = release.get("VERSION_ID", "").strip()
    runtime_values = (
        pillow_version.strip(),
        runner_image,
        runner_image_version,
        ubuntu_id,
        ubuntu_version,
    )
    if not all(runtime_values):
        raise TierCContractError("logical-freeze candidate runtime attestation is incomplete")
    font_files = tuple(current_font_identities())
    font_paths = [font.path for font in font_files]
    fonts_are_unique_and_sorted = font_paths == sorted(set(font_paths))
    if not font_paths or not fonts_are_unique_and_sorted:
        raise TierCContractError("logical-freeze candidate font identities are invalid")
    return CandidateRuntimeAttestation(
        uv_version=EXPECTED_UV,
        pillow_version=pillow_version,
        uv_lock_sha256=sha256_file(REPO_ROOT / "uv.lock"),
        ubuntu_id=ubuntu_id,
        ubuntu_version=ubuntu_version,
        runner_image=runner_image,
        runner_image_version=runner_image_version,
        font_files=font_files,
    )


def _outside_repository(path: Path) -> Path:
    destination = path.expanduser().absolute()
    if destination.resolve(strict=False).is_relative_to(REPO_ROOT.resolve(strict=True)):
        raise TierCContractError("logical-freeze candidates must be written outside the repository")
    if destination.exists():
        raise TierCContractError(f"logical-freeze candidate output already exists: {destination}")
    return destination


def _build_verified_copy(root: Path) -> VerifiedCanonicalSplit:
    build_tier_c(root, dataset=SAFETY_DATASET)
    return load_verified_generated_split(root, SAFETY_DATASET, SAFETY_SPLIT)


def build_candidate(output: Path, *, runtime_attestation: CandidateRuntimeAttestation) -> str:
    """Generate twice and publish only a deterministic, untrusted logical projection."""
    destination = _outside_repository(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if platform.python_version() != EXPECTED_PYTHON:
        raise TierCContractError(f"logical-freeze candidate requires Python {EXPECTED_PYTHON}")
    commit = _git_commit()
    github_sha = os.environ["GITHUB_SHA"]
    if commit != github_sha:
        raise TierCContractError("candidate checkout does not match GITHUB_SHA")

    with tempfile.TemporaryDirectory(prefix="ssi-logical-freeze-source-") as temporary:
        temporary_root = Path(temporary)
        first = _build_verified_copy(temporary_root / "first")
        second = _build_verified_copy(temporary_root / "second")
        first_entries = first.entries
        second_entries = second.entries
        if len(first_entries) != SAFETY_COUNT or len(second_entries) != SAFETY_COUNT:
            raise TierCContractError(
                f"logical-freeze candidate must contain exactly {SAFETY_COUNT} entries"
            )
        first_projection = logical_freeze_projection(first_entries)
        second_projection = logical_freeze_projection(second_entries)
        content = canonical_logical_freeze_bytes(first_projection)
        if content != canonical_logical_freeze_bytes(second_projection):
            raise TierCContractError("independent logical-freeze candidate generations differ")
        if first.meta.git_commit != commit or second.meta.git_commit != commit:
            raise TierCContractError("generated metadata does not match the candidate commit")

        staged = Path(
            tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=destination.parent)
        )
        try:
            freeze_path = default_logical_freeze_path(SAFETY_DATASET, SAFETY_SPLIT)
            if freeze_path is None:
                raise TierCContractError("logical-freeze release path is not configured")
            (staged / freeze_path.name).write_bytes(content)
            provenance = CandidateProvenance.model_validate(
                {
                    "candidate_schema": CANDIDATE_SCHEMA,
                    "status": CANDIDATE_STATUS,
                    "dataset": SAFETY_DATASET,
                    "split": SAFETY_SPLIT,
                    "count": SAFETY_COUNT,
                    "dataset_version": DATASET_VERSION,
                    "manifest_schema": MANIFEST_SCHEMA,
                    "logical_freeze_sha256": logical_freeze_sha256(first_projection),
                    "first_manifest_sha256": first.manifest_sha256,
                    "second_manifest_sha256": second.manifest_sha256,
                    "generator_commit": commit,
                    "github_sha": github_sha,
                    "github_repository": os.environ["GITHUB_REPOSITORY"],
                    "github_event_name": os.environ["GITHUB_EVENT_NAME"],
                    "github_ref": os.environ["GITHUB_REF"],
                    "github_workflow_ref": os.environ["GITHUB_WORKFLOW_REF"],
                    "github_run_id": os.environ["GITHUB_RUN_ID"],
                    "github_run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
                    "python_version": platform.python_version(),
                    **runtime_attestation.provenance_fields(),
                }
            )
            (staged / PROVENANCE_NAME).write_bytes(
                canonical_json_bytes(provenance.model_dump(mode="json"), pretty=True)
            )
            _publish_fresh_tree(staged, destination)
        finally:
            if staged.exists():
                shutil.rmtree(staged)
    return logical_freeze_sha256(first_projection)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Propose an untrusted v1.1 logical safety freeze.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        release = require_proposal_environment()
        runtime_attestation = collect_candidate_runtime(release)
        digest = build_candidate(args.output, runtime_attestation=runtime_attestation)
    except (KeyError, OSError, TierCContractError, ValueError) as exc:
        print(f"UNTRUSTED LOGICAL FREEZE CANDIDATE REFUSED: {exc}", file=sys.stderr)
        return 1
    print(
        "UNTRUSTED logical-freeze candidate built; this is not release evidence: "
        f"sha256={digest}, output={args.output}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
