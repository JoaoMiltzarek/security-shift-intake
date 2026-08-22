"""Emit an explicitly untrusted logical-freeze candidate on canonical Ubuntu."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from data.canonical_io import canonical_json_bytes
from data.generators.tier_c import (
    DATASET_VERSION,
    MANIFEST_SCHEMA,
    _publish_fresh_tree,
    build_tier_c,
)
from data.safety_corpus import EXPECTED_PYTHON, SAFETY_COUNT, SAFETY_DATASET, SAFETY_SPLIT
from data.tier_c_contract import (
    TierCContractError,
    VerifiedCanonicalSplit,
    canonical_logical_freeze_bytes,
    default_logical_freeze_path,
    load_verified_generated_split,
    logical_freeze_projection,
    logical_freeze_sha256,
)
from scripts.build_safety_corpus import require_canonical_builder_environment
from src.paths import REPO_ROOT

CANDIDATE_SCHEMA = "ssi-logical-freeze-candidate/v1"
CANDIDATE_STATUS = "UNTRUSTED_NOT_RELEASE_EVIDENCE"
PROVENANCE_NAME = "candidate-provenance.json"


def _git_commit() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise TierCContractError("cannot identify the logical-freeze candidate commit") from exc
    return completed.stdout.strip()


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


def build_candidate(output: Path) -> str:
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
            provenance = {
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
                "github_workflow_ref": os.environ["GITHUB_WORKFLOW_REF"],
                "github_run_id": os.environ["GITHUB_RUN_ID"],
                "github_run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
                "python_version": platform.python_version(),
            }
            (staged / PROVENANCE_NAME).write_bytes(canonical_json_bytes(provenance, pretty=True))
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
        require_canonical_builder_environment()
        digest = build_candidate(args.output)
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
