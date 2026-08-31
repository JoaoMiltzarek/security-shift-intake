"""Authentication tests for the safety corpus privacy exception."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from data.safety_corpus import inventory_pin_bytes, parse_inventory_pin
from data.tier_c_contract import (
    TierCContractError,
    TierCLogicalFreezeEntry,
    canonical_logical_freeze_bytes,
)
from scripts import privacy_policy as policy

_MEMBER_BYTES = {
    "gt/tc-000000.json": b'{"synthetic":true}\n',
    "manifests/val.jsonl": b"frozen-contract\n",
    "meta.json": b'{"dataset":"bench-balanced"}\n',
    "pngs/tc-000000.png": b"synthetic-png\n",
    "provenance.json": b'{"corpus_schema":"ssi-safety-corpus/v1"}\n',
}


def _git(repo: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        input=input_bytes,
    ).stdout


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.name", "Privacy Test")
    _git(repo, "config", "user.email", "privacy@example.invalid")


def _commit_baseline(repository_root: Path) -> None:
    baseline = repository_root / "README.md"
    baseline.write_text("fixture\n", encoding="utf-8")
    _git(repository_root, "add", "--", "README.md")
    _git(repository_root, "commit", "--quiet", "-m", "baseline fixture")


def _inventory_bytes(members: dict[str, bytes] = _MEMBER_BYTES) -> bytes:
    lines = [
        f"{hashlib.sha256(content).hexdigest()}  {path}"
        for path, content in sorted(members.items())
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _logical_freeze_bytes(count: int = policy.SAFETY_COUNT) -> bytes:
    entries = [
        TierCLogicalFreezeEntry(
            doc_id=f"tc-{index:06d}",
            split="val",
            image=f"pngs/tc-{index:06d}.png",
            gt=f"gt/tc-{index:06d}.json",
            sha256_gt=hashlib.sha256(f"gt-{index}".encode()).hexdigest(),
        )
        for index in range(count)
    ]
    return canonical_logical_freeze_bytes(entries)


def _write_logical_freeze(repository_root: Path, content: bytes | None = None) -> Path:
    freeze = repository_root / policy.SAFETY_LOGICAL_FREEZE_RELATIVE
    freeze.parent.mkdir(parents=True, exist_ok=True)
    freeze.write_bytes(_logical_freeze_bytes() if content is None else content)
    return freeze


def _write_pin(repository_root: Path, inventory: bytes) -> Path:
    pin = repository_root / policy.SAFETY_CORPUS_PIN_RELATIVE
    pin.parent.mkdir(parents=True, exist_ok=True)
    pin.write_bytes(inventory_pin_bytes(hashlib.sha256(inventory).hexdigest()))
    return pin


def _write_corpus(repository_root: Path) -> Path:
    corpus = repository_root / policy.SAFETY_CORPUS_RELATIVE
    for relative, content in _MEMBER_BYTES.items():
        destination = corpus.joinpath(*relative.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    inventory = _inventory_bytes()
    (corpus / "SHA256SUMS").write_bytes(inventory)
    _write_pin(repository_root, inventory)
    return corpus


def _fake_validator(root: Path, *, pin_path: Path, logical_freeze_path: Path) -> Any:
    try:
        if logical_freeze_path.read_bytes() != _logical_freeze_bytes():
            raise ValueError("logical freeze mismatch")
        inventory_bytes = root.joinpath("SHA256SUMS").read_bytes()
        if (
            parse_inventory_pin(pin_path.read_bytes())
            != hashlib.sha256(inventory_bytes).hexdigest()
        ):
            raise ValueError("external pin mismatch")
        inventory = inventory_bytes.decode("utf-8").splitlines()
        expected: dict[str, str] = {}
        for line in inventory:
            digest, relative = line.split("  ", maxsplit=1)
            if relative.startswith("/") or ".." in Path(relative).parts:
                raise ValueError("non-portable inventory path")
            expected[relative] = digest
        actual = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and path.name != "SHA256SUMS"
        }
        if actual != set(expected) or set(expected) != set(_MEMBER_BYTES):
            raise ValueError("inventory coverage mismatch")
        for relative, digest in expected.items():
            content = root.joinpath(*relative.split("/")).read_bytes()
            if hashlib.sha256(content).hexdigest() != digest:
                raise ValueError("inventory hash mismatch")
        if (root / "manifests" / "val.jsonl").read_bytes() != b"frozen-contract\n":
            raise ValueError("freeze mismatch")
    except (OSError, UnicodeError, ValueError) as exc:
        raise TierCContractError("fixture contract rejected") from exc
    entry = SimpleNamespace(image="pngs/tc-000000.png", gt="gt/tc-000000.json")
    return SimpleNamespace(split=SimpleNamespace(entries=(entry,)))


def _commit_pin(repository_root: Path) -> None:
    _write_logical_freeze(repository_root)
    _git(repository_root, "add", "--", policy.SAFETY_LOGICAL_FREEZE_RELATIVE.as_posix())
    _git(repository_root, "commit", "--quiet", "-m", "freeze fixture")
    _git(repository_root, "add", "--", policy.SAFETY_CORPUS_PIN_RELATIVE.as_posix())
    _git(repository_root, "commit", "--quiet", "-m", "pin fixture")


def _commit_logical_freeze(repository_root: Path) -> None:
    _write_logical_freeze(repository_root)
    _git(repository_root, "add", "--", policy.SAFETY_LOGICAL_FREEZE_RELATIVE.as_posix())
    _git(repository_root, "commit", "--quiet", "-m", "freeze fixture")


def _write_trusted_worktree_corpus(repository_root: Path) -> Path:
    _init_repo(repository_root)
    corpus = _write_corpus(repository_root)
    _commit_pin(repository_root)
    return corpus


@pytest.fixture(autouse=True)
def _use_minimal_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(policy, "load_verified_safety_corpus", _fake_validator)


def test_worktree_authentication_returns_only_exact_hashed_members(tmp_path: Path) -> None:
    _write_trusted_worktree_corpus(tmp_path)

    authenticated = policy.authenticate_worktree_safety_corpus(tmp_path)

    image = policy.SAFETY_CORPUS_RELATIVE / "pngs" / "tc-000000.png"
    assert authenticated.accepts(image, _MEMBER_BYTES["pngs/tc-000000.png"])
    assert not authenticated.accepts(image, b"different")
    assert not authenticated.accepts(Path("data/other.png"), b"synthetic-png\n")
    assert len(authenticated.members) == len(_MEMBER_BYTES) + 1


def test_worktree_authentication_rejects_extra_member(tmp_path: Path) -> None:
    corpus = _write_trusted_worktree_corpus(tmp_path)
    (corpus / "extra.png").write_bytes(b"extra")

    with pytest.raises(policy.CorpusPrivacyError, match="validation failed"):
        policy.authenticate_worktree_safety_corpus(tmp_path)


def test_worktree_authentication_rejects_partial_corpus(tmp_path: Path) -> None:
    corpus = _write_trusted_worktree_corpus(tmp_path)
    (corpus / "gt" / "tc-000000.json").unlink()

    with pytest.raises(policy.CorpusPrivacyError, match="validation failed"):
        policy.authenticate_worktree_safety_corpus(tmp_path)


def test_worktree_authentication_rejects_inventory_hash_drift(tmp_path: Path) -> None:
    corpus = _write_trusted_worktree_corpus(tmp_path)
    (corpus / "pngs" / "tc-000000.png").write_bytes(b"changed")

    with pytest.raises(policy.CorpusPrivacyError, match="validation failed"):
        policy.authenticate_worktree_safety_corpus(tmp_path)


def test_worktree_authentication_rejects_inventory_path_traversal(tmp_path: Path) -> None:
    corpus = _write_trusted_worktree_corpus(tmp_path)
    digest = hashlib.sha256(b"escape").hexdigest()
    (corpus / "SHA256SUMS").write_text(f"{digest}  ../escape.png\n", encoding="utf-8", newline="\n")

    with pytest.raises(policy.CorpusPrivacyError, match="validation failed"):
        policy.authenticate_worktree_safety_corpus(tmp_path)


def test_worktree_authentication_rejects_reparse_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = _write_trusted_worktree_corpus(tmp_path)
    redirected = corpus / "pngs" / "tc-000000.png"
    original = policy._is_redirected
    monkeypatch.setattr(
        policy,
        "_is_redirected",
        lambda candidate: candidate == redirected or original(candidate),
    )

    with pytest.raises(policy.CorpusPrivacyError, match="redirected member"):
        policy.authenticate_worktree_safety_corpus(tmp_path)


def test_index_authentication_uses_complete_matching_snapshot(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write_corpus(tmp_path)
    _commit_pin(tmp_path)
    _git(tmp_path, "add", "--", policy.SAFETY_CORPUS_RELATIVE.as_posix())

    authenticated = policy.authenticate_index_safety_corpus(tmp_path)

    assert len(authenticated.members) == len(_MEMBER_BYTES) + 1


def test_index_authentication_rejects_partial_staging(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write_corpus(tmp_path)
    _commit_pin(tmp_path)
    one_member = policy.SAFETY_CORPUS_RELATIVE / "pngs" / "tc-000000.png"
    _git(tmp_path, "add", "--", one_member.as_posix())

    with pytest.raises(policy.CorpusPrivacyError, match="worktree differs"):
        policy.authenticate_index_safety_corpus(tmp_path)


def test_index_authentication_rejects_untracked_worktree_extra(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    corpus = _write_corpus(tmp_path)
    _commit_pin(tmp_path)
    _git(tmp_path, "add", "--", policy.SAFETY_CORPUS_RELATIVE.as_posix())
    (corpus / "extra.png").write_bytes(b"extra")

    with pytest.raises(policy.CorpusPrivacyError, match="worktree differs"):
        policy.authenticate_index_safety_corpus(tmp_path)


def test_index_authentication_rejects_worktree_bytes_different_from_index(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    corpus = _write_corpus(tmp_path)
    _commit_pin(tmp_path)
    _git(tmp_path, "add", "--", policy.SAFETY_CORPUS_RELATIVE.as_posix())
    (corpus / "pngs" / "tc-000000.png").write_bytes(b"unstaged replacement")

    with pytest.raises(policy.CorpusPrivacyError, match="worktree differs"):
        policy.authenticate_index_safety_corpus(tmp_path)


def test_index_authentication_rejects_symlink_mode(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write_corpus(tmp_path)
    _commit_pin(tmp_path)
    _git(tmp_path, "add", "--", policy.SAFETY_CORPUS_RELATIVE.as_posix())
    member = policy.SAFETY_CORPUS_RELATIVE / "pngs" / "tc-000000.png"
    object_id = (
        _git(tmp_path, "hash-object", "-w", "--stdin", input_bytes=b"target")
        .decode("ascii")
        .strip()
    )
    _git(
        tmp_path,
        "update-index",
        "--add",
        "--cacheinfo",
        "120000",
        object_id,
        member.as_posix(),
    )

    with pytest.raises(policy.CorpusPrivacyError, match="regular file"):
        policy.authenticate_index_safety_corpus(tmp_path)


def test_index_authentication_rejects_pin_not_committed_in_head(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit_logical_freeze(tmp_path)
    _write_corpus(tmp_path)
    _git(tmp_path, "add", "--", "data")

    with pytest.raises(policy.CorpusPrivacyError, match="not committed in HEAD"):
        policy.authenticate_index_safety_corpus(tmp_path)


def test_index_authentication_rejects_unstaged_pin_change(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write_corpus(tmp_path)
    _commit_pin(tmp_path)
    _git(tmp_path, "add", "--", policy.SAFETY_CORPUS_RELATIVE.as_posix())
    pin = tmp_path / policy.SAFETY_CORPUS_PIN_RELATIVE
    pin.write_bytes(inventory_pin_bytes(hashlib.sha256(b"replacement").hexdigest()))

    with pytest.raises(policy.CorpusPrivacyError, match="worktree differs from HEAD"):
        policy.authenticate_index_safety_corpus(tmp_path)


def test_index_authentication_rejects_inventory_outside_head_pin(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write_corpus(tmp_path)
    pin = tmp_path / policy.SAFETY_CORPUS_PIN_RELATIVE
    pin.write_bytes(inventory_pin_bytes(hashlib.sha256(b"different inventory").hexdigest()))
    _commit_pin(tmp_path)
    _git(tmp_path, "add", "--", policy.SAFETY_CORPUS_RELATIVE.as_posix())

    with pytest.raises(policy.CorpusPrivacyError, match="validation failed"):
        policy.authenticate_index_safety_corpus(tmp_path)


def test_initial_logical_freeze_is_valid_only_as_a_canonical_freeze_only_delta(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    _commit_baseline(tmp_path)
    _write_logical_freeze(tmp_path)
    _git(tmp_path, "add", "--", policy.SAFETY_LOGICAL_FREEZE_RELATIVE.as_posix())

    policy.validate_staged_logical_freeze(
        tmp_path,
        pin_changed=False,
        corpus_changed=False,
    )


def test_initial_logical_freeze_requires_exactly_45_entries(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit_baseline(tmp_path)
    _write_logical_freeze(tmp_path, _logical_freeze_bytes(count=44))
    _git(tmp_path, "add", "--", policy.SAFETY_LOGICAL_FREEZE_RELATIVE.as_posix())

    with pytest.raises(policy.CorpusPrivacyError, match="44 entries, expected 45"):
        policy.validate_staged_logical_freeze(
            tmp_path,
            pin_changed=False,
            corpus_changed=False,
        )


def test_initial_logical_freeze_rejects_another_staged_file(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit_baseline(tmp_path)
    _write_logical_freeze(tmp_path)
    (tmp_path / "notes.txt").write_text("unrelated\n", encoding="utf-8")
    _git(tmp_path, "add", "--", policy.SAFETY_LOGICAL_FREEZE_RELATIVE.as_posix(), "notes.txt")

    with pytest.raises(policy.CorpusPrivacyError, match="only staged delta"):
        policy.validate_staged_logical_freeze(
            tmp_path,
            pin_changed=False,
            corpus_changed=False,
        )


def test_initial_logical_freeze_rejects_a_staged_pin(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit_baseline(tmp_path)
    _write_logical_freeze(tmp_path)
    _write_pin(tmp_path, _inventory_bytes())
    _git(tmp_path, "add", "--", "data/manifests")

    with pytest.raises(policy.CorpusPrivacyError, match="separate commits"):
        policy.validate_staged_logical_freeze(
            tmp_path,
            pin_changed=True,
            corpus_changed=False,
        )


def test_initial_logical_freeze_rejects_a_staged_corpus(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit_baseline(tmp_path)
    _write_logical_freeze(tmp_path)
    corpus = _write_corpus(tmp_path)
    _git(tmp_path, "add", "--", policy.SAFETY_LOGICAL_FREEZE_RELATIVE.as_posix())
    _git(tmp_path, "add", "--", corpus.relative_to(tmp_path).as_posix())

    with pytest.raises(policy.CorpusPrivacyError, match="separate commits"):
        policy.validate_staged_logical_freeze(
            tmp_path,
            pin_changed=False,
            corpus_changed=True,
        )


@pytest.mark.parametrize("operation", ["modify", "delete"])
def test_committed_logical_freeze_is_write_once(tmp_path: Path, operation: str) -> None:
    _init_repo(tmp_path)
    _commit_logical_freeze(tmp_path)
    freeze = tmp_path / policy.SAFETY_LOGICAL_FREEZE_RELATIVE
    if operation == "modify":
        freeze.write_bytes(_logical_freeze_bytes(count=44))
        _git(tmp_path, "add", "--", policy.SAFETY_LOGICAL_FREEZE_RELATIVE.as_posix())
    else:
        _git(tmp_path, "rm", "--quiet", "--", policy.SAFETY_LOGICAL_FREEZE_RELATIVE.as_posix())

    with pytest.raises(policy.CorpusPrivacyError, match="write-once"):
        policy.validate_staged_logical_freeze(
            tmp_path,
            pin_changed=False,
            corpus_changed=False,
        )


def test_corpus_rejects_an_untracked_logical_freeze(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    corpus = _write_corpus(tmp_path)
    _git(tmp_path, "add", "--", policy.SAFETY_CORPUS_PIN_RELATIVE.as_posix())
    _git(tmp_path, "commit", "--quiet", "-m", "pin without freeze")
    _write_logical_freeze(tmp_path)
    _git(tmp_path, "add", "--", corpus.relative_to(tmp_path).as_posix())

    with pytest.raises(policy.CorpusPrivacyError, match="not committed in HEAD"):
        policy.authenticate_index_safety_corpus(tmp_path)


def test_corpus_rejects_a_logical_freeze_staged_in_the_same_delta(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    corpus = _write_corpus(tmp_path)
    _git(tmp_path, "add", "--", policy.SAFETY_CORPUS_PIN_RELATIVE.as_posix())
    _git(tmp_path, "commit", "--quiet", "-m", "pin without freeze")
    _write_logical_freeze(tmp_path)
    _git(tmp_path, "add", "--", policy.SAFETY_LOGICAL_FREEZE_RELATIVE.as_posix())
    _git(tmp_path, "add", "--", corpus.relative_to(tmp_path).as_posix())

    with pytest.raises(policy.CorpusPrivacyError, match="not committed in HEAD"):
        policy.authenticate_index_safety_corpus(tmp_path)


def test_corpus_rejects_logical_freeze_index_drift(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    corpus = _write_corpus(tmp_path)
    _commit_pin(tmp_path)
    _git(tmp_path, "add", "--", corpus.relative_to(tmp_path).as_posix())
    freeze = tmp_path / policy.SAFETY_LOGICAL_FREEZE_RELATIVE
    committed = freeze.read_bytes()
    freeze.write_bytes(_logical_freeze_bytes(count=44))
    _git(tmp_path, "add", "--", policy.SAFETY_LOGICAL_FREEZE_RELATIVE.as_posix())
    freeze.write_bytes(committed)

    with pytest.raises(policy.CorpusPrivacyError, match="index differs from HEAD"):
        policy.authenticate_index_safety_corpus(tmp_path)


def test_corpus_rejects_logical_freeze_worktree_drift(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    corpus = _write_corpus(tmp_path)
    _commit_pin(tmp_path)
    _git(tmp_path, "add", "--", corpus.relative_to(tmp_path).as_posix())
    freeze = tmp_path / policy.SAFETY_LOGICAL_FREEZE_RELATIVE
    freeze.write_bytes(_logical_freeze_bytes(count=44))

    with pytest.raises(policy.CorpusPrivacyError, match="worktree differs from HEAD"):
        policy.authenticate_index_safety_corpus(tmp_path)


def test_corpus_rejects_logical_freeze_index_mode_drift(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    corpus = _write_corpus(tmp_path)
    _commit_pin(tmp_path)
    _git(tmp_path, "add", "--", corpus.relative_to(tmp_path).as_posix())
    _git(
        tmp_path,
        "update-index",
        "--chmod=+x",
        "--",
        policy.SAFETY_LOGICAL_FREEZE_RELATIVE.as_posix(),
    )

    with pytest.raises(policy.CorpusPrivacyError, match="regular 100644"):
        policy.authenticate_index_safety_corpus(tmp_path)


def test_corpus_rejects_external_pin_index_drift(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    corpus = _write_corpus(tmp_path)
    _commit_pin(tmp_path)
    _git(tmp_path, "add", "--", corpus.relative_to(tmp_path).as_posix())
    pin = tmp_path / policy.SAFETY_CORPUS_PIN_RELATIVE
    committed = pin.read_bytes()
    pin.write_bytes(inventory_pin_bytes(hashlib.sha256(b"replacement").hexdigest()))
    _git(tmp_path, "add", "--", policy.SAFETY_CORPUS_PIN_RELATIVE.as_posix())
    pin.write_bytes(committed)

    with pytest.raises(policy.CorpusPrivacyError, match="pin index differs from HEAD"):
        policy.authenticate_index_safety_corpus(tmp_path)


def test_corpus_rejects_external_pin_index_mode_drift(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    corpus = _write_corpus(tmp_path)
    _commit_pin(tmp_path)
    _git(tmp_path, "add", "--", corpus.relative_to(tmp_path).as_posix())
    _git(
        tmp_path,
        "update-index",
        "--chmod=+x",
        "--",
        policy.SAFETY_CORPUS_PIN_RELATIVE.as_posix(),
    )

    with pytest.raises(policy.CorpusPrivacyError, match="regular 100644"):
        policy.authenticate_index_safety_corpus(tmp_path)


def test_initial_staged_pin_is_valid_only_before_the_corpus(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit_logical_freeze(tmp_path)
    _write_pin(tmp_path, _inventory_bytes())
    _git(tmp_path, "add", "--", policy.SAFETY_CORPUS_PIN_RELATIVE.as_posix())

    policy.validate_staged_inventory_pin(tmp_path, corpus_changed=False)


def test_initial_staged_pin_rejects_another_staged_file(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit_logical_freeze(tmp_path)
    _write_pin(tmp_path, _inventory_bytes())
    (tmp_path / "notes.txt").write_text("unrelated\n", encoding="utf-8")
    _git(tmp_path, "add", "--", policy.SAFETY_CORPUS_PIN_RELATIVE.as_posix(), "notes.txt")

    with pytest.raises(policy.CorpusPrivacyError, match="only staged delta"):
        policy.validate_staged_inventory_pin(tmp_path, corpus_changed=False)


def test_initial_staged_pin_requires_the_logical_freeze_in_head(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit_baseline(tmp_path)
    _write_pin(tmp_path, _inventory_bytes())
    _git(tmp_path, "add", "--", policy.SAFETY_CORPUS_PIN_RELATIVE.as_posix())

    with pytest.raises(policy.CorpusPrivacyError, match="not committed in HEAD"):
        policy.validate_staged_inventory_pin(tmp_path, corpus_changed=False)


def test_initial_staged_pin_rejects_logical_freeze_worktree_drift(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit_logical_freeze(tmp_path)
    _write_pin(tmp_path, _inventory_bytes())
    _git(tmp_path, "add", "--", policy.SAFETY_CORPUS_PIN_RELATIVE.as_posix())
    freeze = tmp_path / policy.SAFETY_LOGICAL_FREEZE_RELATIVE
    freeze.write_bytes(_logical_freeze_bytes(count=44))

    with pytest.raises(policy.CorpusPrivacyError, match="worktree differs from HEAD"):
        policy.validate_staged_inventory_pin(tmp_path, corpus_changed=False)


def test_staged_logical_freeze_and_pin_are_rejected_by_the_pin_guard(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit_baseline(tmp_path)
    _write_logical_freeze(tmp_path)
    _write_pin(tmp_path, _inventory_bytes())
    _git(tmp_path, "add", "--", "data/manifests")

    with pytest.raises(policy.CorpusPrivacyError, match="separate commits"):
        policy.validate_staged_inventory_pin(
            tmp_path,
            corpus_changed=False,
            freeze_changed=True,
        )


def test_staged_pin_and_corpus_in_one_delta_are_rejected(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit_logical_freeze(tmp_path)
    _write_corpus(tmp_path)
    _git(tmp_path, "add", "--", "data")

    with pytest.raises(policy.CorpusPrivacyError, match="separate commits"):
        policy.validate_staged_inventory_pin(tmp_path, corpus_changed=True)


def test_committed_pin_is_write_once(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    pin = _write_pin(tmp_path, _inventory_bytes())
    _commit_pin(tmp_path)
    pin.write_bytes(inventory_pin_bytes(hashlib.sha256(b"replacement").hexdigest()))
    _git(tmp_path, "add", "--", policy.SAFETY_CORPUS_PIN_RELATIVE.as_posix())

    with pytest.raises(policy.CorpusPrivacyError, match="write-once"):
        policy.validate_staged_inventory_pin(tmp_path, corpus_changed=False)


def test_committed_pin_deletion_is_rejected(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write_pin(tmp_path, _inventory_bytes())
    _commit_pin(tmp_path)
    _git(tmp_path, "rm", "--quiet", "--", policy.SAFETY_CORPUS_PIN_RELATIVE.as_posix())

    with pytest.raises(policy.CorpusPrivacyError, match="write-once"):
        policy.validate_staged_inventory_pin(tmp_path, corpus_changed=False)


def test_new_pin_cannot_follow_an_already_indexed_corpus(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit_logical_freeze(tmp_path)
    corpus = _write_corpus(tmp_path)
    pin = tmp_path / policy.SAFETY_CORPUS_PIN_RELATIVE
    pin.unlink()
    _git(tmp_path, "add", "--", policy.SAFETY_CORPUS_RELATIVE.as_posix())
    _git(tmp_path, "commit", "--quiet", "-m", "untrusted corpus fixture")
    _write_pin(tmp_path, (corpus / "SHA256SUMS").read_bytes())
    _git(tmp_path, "add", "--", policy.SAFETY_CORPUS_PIN_RELATIVE.as_posix())

    with pytest.raises(policy.CorpusPrivacyError, match="must precede"):
        policy.validate_staged_inventory_pin(tmp_path, corpus_changed=False)
