"""Read-only verification for downloaded logical-freeze proposals."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from data.canonical_io import canonical_json_bytes
from data.generators.tier_c import DATASET_VERSION, MANIFEST_SCHEMA
from data.safety_corpus import SAFETY_COUNT, CorpusFontIdentity
from data.tier_c_contract import (
    TierCContractError,
    TierCLogicalFreezeEntry,
    canonical_logical_freeze_bytes,
    logical_freeze_sha256,
)
from scripts import verify_logical_freeze_candidate as verifier
from scripts.propose_safety_logical_freeze import (
    CANDIDATE_SCHEMA,
    CANDIDATE_STATUS,
    PROVENANCE_NAME,
)

COMMIT = "a" * 40
FONTS = [
    CorpusFontIdentity(path="assets/fonts/First.ttf", sha256="1" * 64),
    CorpusFontIdentity(path="assets/fonts/Second.ttf", sha256="2" * 64),
]


def _entries() -> tuple[TierCLogicalFreezeEntry, ...]:
    return tuple(
        TierCLogicalFreezeEntry(
            doc_id=f"tc-{index:06d}",
            split="val",
            image=f"pngs/tc-{index:06d}.png",
            gt=f"gt/tc-{index:06d}.json",
            sha256_gt=hashlib.sha256(f"gt-{index}".encode()).hexdigest(),
        )
        for index in range(SAFETY_COUNT)
    )


def _provenance(entries: tuple[TierCLogicalFreezeEntry, ...]) -> dict[str, object]:
    github_ref = "refs/heads/main"
    return {
        "candidate_schema": CANDIDATE_SCHEMA,
        "status": CANDIDATE_STATUS,
        "dataset": "bench-balanced",
        "split": "val",
        "count": SAFETY_COUNT,
        "dataset_version": DATASET_VERSION,
        "manifest_schema": MANIFEST_SCHEMA,
        "logical_freeze_sha256": logical_freeze_sha256(entries),
        "first_manifest_sha256": "3" * 64,
        "second_manifest_sha256": "4" * 64,
        "generator_commit": COMMIT,
        "github_sha": COMMIT,
        "github_repository": "JoaoMiltzarek/security-shift-intake",
        "github_event_name": "workflow_dispatch",
        "github_ref": github_ref,
        "github_workflow_ref": (
            "JoaoMiltzarek/security-shift-intake/.github/workflows/"
            f"propose-safety-logical-freeze.yml@{github_ref}"
        ),
        "github_run_id": "123",
        "github_run_attempt": "1",
        "python_version": "3.11.15",
        "uv_version": "0.11.28",
        "pillow_version": "12.3.0",
        "uv_lock_sha256": "5" * 64,
        "ubuntu_id": "ubuntu",
        "ubuntu_version": "24.04",
        "runner_image": "ubuntu24",
        "runner_image_version": "20260817.1",
        "font_files": [font.model_dump(mode="json") for font in FONTS],
    }


def _write_candidate(root: Path) -> tuple[Path, Path]:
    root.mkdir()
    entries = _entries()
    freeze = root / "bench-balanced.val.logical.jsonl"
    provenance = root / PROVENANCE_NAME
    freeze.write_bytes(canonical_logical_freeze_bytes(entries))
    provenance.write_bytes(canonical_json_bytes(_provenance(entries), pretty=True))
    return freeze, provenance


def _checkout_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verifier, "_git_commit", lambda: COMMIT)
    monkeypatch.setattr(verifier, "sha256_file", lambda _path: "5" * 64)
    monkeypatch.setattr(verifier, "current_font_identities", lambda: FONTS)


def test_candidate_verifier_accepts_exact_bytes_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = tmp_path / "candidate"
    _write_candidate(candidate)
    _checkout_identity(monkeypatch)
    before = {path.name: path.read_bytes() for path in candidate.iterdir()}

    provenance = verifier.verify_candidate(candidate)

    assert provenance.logical_freeze_sha256 == logical_freeze_sha256(_entries())
    assert {path.name: path.read_bytes() for path in candidate.iterdir()} == before


def test_candidate_verifier_rejects_freeze_hash_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = tmp_path / "candidate"
    freeze, _ = _write_candidate(candidate)
    changed = list(_entries())
    changed[0] = changed[0].model_copy(update={"sha256_gt": "f" * 64})
    freeze.write_bytes(canonical_logical_freeze_bytes(changed))
    _checkout_identity(monkeypatch)

    with pytest.raises(TierCContractError, match="hash differs"):
        verifier.verify_candidate(candidate)


def test_candidate_verifier_rejects_extra_or_noncanonical_members(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = tmp_path / "candidate"
    _, provenance = _write_candidate(candidate)
    _checkout_identity(monkeypatch)
    (candidate / "extra.txt").write_text("extra\n", encoding="utf-8")
    with pytest.raises(TierCContractError, match="members are not exact"):
        verifier.verify_candidate(candidate)

    (candidate / "extra.txt").unlink()
    content = provenance.read_bytes()
    duplicate = (
        b'{\n  "candidate_schema": "ssi-logical-freeze-candidate/v1",\n'
        + content.removeprefix(b"{\n")
    )
    provenance.write_bytes(duplicate)
    with pytest.raises(TierCContractError, match="provenance JSON is invalid"):
        verifier.verify_candidate(candidate)


@pytest.mark.parametrize(
    ("identity", "message"),
    [
        ("commit", "commit differs"),
        ("lock", "lockfile identity differs"),
        ("fonts", "font identities differ"),
    ],
)
def test_candidate_verifier_rejects_checkout_identity_drift(
    identity: str,
    message: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate"
    _write_candidate(candidate)
    _checkout_identity(monkeypatch)
    if identity == "commit":
        monkeypatch.setattr(verifier, "_git_commit", lambda: "b" * 40)
    elif identity == "lock":
        monkeypatch.setattr(verifier, "sha256_file", lambda _path: "6" * 64)
    else:
        monkeypatch.setattr(verifier, "current_font_identities", lambda: FONTS[:1])

    with pytest.raises(TierCContractError, match=message):
        verifier.verify_candidate(candidate)


def test_candidate_verifier_cli_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert verifier.main(["--candidate", str(tmp_path / "missing")]) == 1
    assert "LOGICAL FREEZE CANDIDATE REFUSED" in capsys.readouterr().err
