"""Contracts for the untrusted two-generation logical-freeze proposal."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from data.safety_corpus import SAFETY_COUNT
from data.tier_c_contract import TierCContractError, TierCManifestEntry
from scripts import propose_safety_logical_freeze as proposal
from src.paths import REPO_ROOT


def _verified(*, image_hash: str, gt_hash: str, commit: str) -> SimpleNamespace:
    entries = tuple(
        TierCManifestEntry(
            doc_id=f"tc-{index:06d}",
            split="val",
            image=f"pngs/tc-{index:06d}.png",
            gt=f"gt/tc-{index:06d}.json",
            sha256_img=image_hash,
            sha256_gt=gt_hash,
        )
        for index in range(SAFETY_COUNT)
    )
    return SimpleNamespace(
        entries=entries,
        manifest_sha256=image_hash,
        meta=SimpleNamespace(git_commit=commit),
    )


def _candidate_environment(monkeypatch: pytest.MonkeyPatch, commit: str) -> None:
    monkeypatch.setenv("GITHUB_SHA", commit)
    monkeypatch.setenv("GITHUB_REPOSITORY", "JoaoMiltzarek/security-shift-intake")
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", "repo/workflow@main")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setattr(proposal, "_git_commit", lambda: commit)


def test_candidate_output_must_stay_outside_the_repository() -> None:
    with pytest.raises(TierCContractError, match="outside the repository"):
        proposal.build_candidate(REPO_ROOT / "candidate-output")


def test_candidate_requires_two_identical_logical_generations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commit = "a" * 40
    _candidate_environment(monkeypatch, commit)
    generated = iter(
        (
            _verified(image_hash="1" * 64, gt_hash="2" * 64, commit=commit),
            _verified(image_hash="3" * 64, gt_hash="4" * 64, commit=commit),
        )
    )
    monkeypatch.setattr(proposal, "_build_verified_copy", lambda _root: next(generated))

    with pytest.raises(TierCContractError, match="generations differ"):
        proposal.build_candidate(tmp_path / "candidate")

    assert not (tmp_path / "candidate").exists()


def test_candidate_publishes_only_untrusted_projection_and_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commit = "a" * 40
    _candidate_environment(monkeypatch, commit)
    generated = iter(
        (
            _verified(image_hash="1" * 64, gt_hash="2" * 64, commit=commit),
            _verified(image_hash="3" * 64, gt_hash="2" * 64, commit=commit),
        )
    )
    roots: list[Path] = []

    def generate(root: Path) -> SimpleNamespace:
        roots.append(root)
        return next(generated)

    monkeypatch.setattr(proposal, "_build_verified_copy", generate)
    output = tmp_path / "candidate"

    digest = proposal.build_candidate(output)

    assert [root.name for root in roots] == ["first", "second"]
    assert {path.name for path in output.iterdir()} == {
        "bench-balanced.val.logical.jsonl",
        proposal.PROVENANCE_NAME,
    }
    freeze = (output / "bench-balanced.val.logical.jsonl").read_text(encoding="utf-8")
    assert "sha256_img" not in freeze
    provenance = json.loads((output / proposal.PROVENANCE_NAME).read_text(encoding="utf-8"))
    assert provenance["status"] == proposal.CANDIDATE_STATUS
    assert provenance["logical_freeze_sha256"] == digest
    assert provenance["first_manifest_sha256"] != provenance["second_manifest_sha256"]
    assert provenance["generator_commit"] == commit


def test_cli_refuses_when_not_in_the_canonical_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def reject() -> None:
        raise TierCContractError("wrong environment")

    monkeypatch.setattr(proposal, "require_canonical_builder_environment", reject)

    assert proposal.main(["--output", str(tmp_path / "candidate")]) == 1
    assert "UNTRUSTED LOGICAL FREEZE CANDIDATE REFUSED" in capsys.readouterr().err
