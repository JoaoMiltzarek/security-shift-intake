"""Verify a downloaded logical-freeze proposal before human acceptance."""

from __future__ import annotations

import argparse
import json
import stat
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from data.canonical_io import canonical_json_bytes
from data.safety_corpus import SAFETY_COUNT, SAFETY_SPLIT, current_font_identities
from data.tier_c_contract import (
    TierCContractError,
    default_logical_freeze_path,
    logical_freeze_sha256,
    parse_logical_freeze,
    sha256_file,
)
from scripts.propose_safety_logical_freeze import (
    PROVENANCE_NAME,
    CandidateProvenance,
    _git_commit,
)
from src.paths import REPO_ROOT


def _is_redirected(path: Path) -> bool:
    metadata = path.lstat()
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & reparse_flag)


def _candidate_files(root: Path) -> dict[str, Path]:
    try:
        metadata = root.lstat()
    except OSError as exc:
        raise TierCContractError("logical-freeze candidate directory is unavailable") from exc
    if _is_redirected(root) or not stat.S_ISDIR(metadata.st_mode):
        raise TierCContractError("logical-freeze candidate root must be a plain directory")
    freeze = default_logical_freeze_path("bench-balanced", "val")
    if freeze is None:
        raise TierCContractError("logical-freeze release path is not configured")
    expected = {freeze.name, PROVENANCE_NAME}
    try:
        members = list(root.iterdir())
    except OSError as exc:
        raise TierCContractError("logical-freeze candidate could not be enumerated") from exc
    if {member.name for member in members} != expected:
        raise TierCContractError("logical-freeze candidate members are not exact")
    result: dict[str, Path] = {}
    for member in members:
        try:
            member_metadata = member.lstat()
        except OSError as exc:
            raise TierCContractError("logical-freeze candidate member is unreadable") from exc
        if _is_redirected(member) or not stat.S_ISREG(member_metadata.st_mode):
            raise TierCContractError("logical-freeze candidate member is not a plain file")
        result[member.name] = member
    return result


def _strict_json_object(content: bytes) -> dict[str, Any]:
    if b"\r" in content or not content.endswith(b"\n"):
        raise TierCContractError("candidate provenance is not canonical LF text")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> None:
        raise ValueError(f"non-finite JSON constant is forbidden: {value}")

    try:
        payload = json.loads(
            content.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_nonfinite,
        )
    except (UnicodeError, ValueError) as exc:
        raise TierCContractError("candidate provenance JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise TierCContractError("candidate provenance must be a JSON object")
    return payload


def verify_candidate(root: Path) -> CandidateProvenance:
    """Authenticate one untrusted proposal against this exact checkout."""
    candidate_root = root.expanduser().absolute()
    members = _candidate_files(candidate_root)
    provenance_path = members[PROVENANCE_NAME]
    try:
        provenance_content = provenance_path.read_bytes()
        provenance = CandidateProvenance.model_validate(_strict_json_object(provenance_content))
    except (OSError, ValidationError) as exc:
        raise TierCContractError("candidate provenance does not satisfy its schema") from exc
    if canonical_json_bytes(provenance.model_dump(mode="json"), pretty=True) != provenance_content:
        raise TierCContractError("candidate provenance is not canonical JSON")

    freeze_path = default_logical_freeze_path(provenance.dataset, provenance.split)
    if freeze_path is None:
        raise TierCContractError("candidate logical-freeze destination is unsupported")
    entries = parse_logical_freeze(
        members[freeze_path.name],
        expected_split=SAFETY_SPLIT,
    )
    if len(entries) != SAFETY_COUNT:
        raise TierCContractError(
            f"candidate logical freeze has {len(entries)} entries, expected {SAFETY_COUNT}"
        )
    if logical_freeze_sha256(entries) != provenance.logical_freeze_sha256:
        raise TierCContractError("candidate logical-freeze hash differs from provenance")
    if provenance.generator_commit != _git_commit():
        raise TierCContractError("candidate commit differs from this checkout")
    if provenance.uv_lock_sha256 != sha256_file(REPO_ROOT / "uv.lock"):
        raise TierCContractError("candidate lockfile identity differs from this checkout")
    if provenance.font_files != current_font_identities():
        raise TierCContractError("candidate font identities differ from this checkout")
    return provenance


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Verify an untrusted logical-freeze candidate before human review."
    )
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        provenance = verify_candidate(args.candidate)
    except (OSError, TierCContractError, ValueError) as exc:
        print(f"LOGICAL FREEZE CANDIDATE REFUSED: {exc}", file=sys.stderr)
        return 1
    print(
        "Candidate validated for human freeze review; still not release evidence: "
        f"sha256={provenance.logical_freeze_sha256}, commit={provenance.generator_commit}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
