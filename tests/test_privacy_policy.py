"""Authentication tests for the safety corpus privacy exception."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from data.tier_c_contract import TierCContractError
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


def _inventory_bytes(members: dict[str, bytes] = _MEMBER_BYTES) -> bytes:
    lines = [
        f"{hashlib.sha256(content).hexdigest()}  {path}"
        for path, content in sorted(members.items())
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _write_corpus(repository_root: Path) -> Path:
    corpus = repository_root / policy.SAFETY_CORPUS_RELATIVE
    for relative, content in _MEMBER_BYTES.items():
        destination = corpus.joinpath(*relative.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    (corpus / "SHA256SUMS").write_bytes(_inventory_bytes())
    return corpus


def _fake_validator(root: Path) -> Any:
    try:
        inventory = root.joinpath("SHA256SUMS").read_text(encoding="utf-8").splitlines()
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


@pytest.fixture(autouse=True)
def _use_minimal_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(policy, "load_verified_safety_corpus", _fake_validator)


def test_worktree_authentication_returns_only_exact_hashed_members(tmp_path: Path) -> None:
    _write_corpus(tmp_path)

    authenticated = policy.authenticate_worktree_safety_corpus(tmp_path)

    image = policy.SAFETY_CORPUS_RELATIVE / "pngs" / "tc-000000.png"
    assert authenticated.accepts(image, _MEMBER_BYTES["pngs/tc-000000.png"])
    assert not authenticated.accepts(image, b"different")
    assert not authenticated.accepts(Path("data/other.png"), b"synthetic-png\n")
    assert len(authenticated.members) == len(_MEMBER_BYTES) + 1


def test_worktree_authentication_rejects_extra_member(tmp_path: Path) -> None:
    corpus = _write_corpus(tmp_path)
    (corpus / "extra.png").write_bytes(b"extra")

    with pytest.raises(policy.CorpusPrivacyError, match="validation failed"):
        policy.authenticate_worktree_safety_corpus(tmp_path)


def test_worktree_authentication_rejects_partial_corpus(tmp_path: Path) -> None:
    corpus = _write_corpus(tmp_path)
    (corpus / "gt" / "tc-000000.json").unlink()

    with pytest.raises(policy.CorpusPrivacyError, match="validation failed"):
        policy.authenticate_worktree_safety_corpus(tmp_path)


def test_worktree_authentication_rejects_inventory_hash_drift(tmp_path: Path) -> None:
    corpus = _write_corpus(tmp_path)
    (corpus / "pngs" / "tc-000000.png").write_bytes(b"changed")

    with pytest.raises(policy.CorpusPrivacyError, match="validation failed"):
        policy.authenticate_worktree_safety_corpus(tmp_path)


def test_worktree_authentication_rejects_inventory_path_traversal(tmp_path: Path) -> None:
    corpus = _write_corpus(tmp_path)
    digest = hashlib.sha256(b"escape").hexdigest()
    (corpus / "SHA256SUMS").write_text(f"{digest}  ../escape.png\n", encoding="utf-8", newline="\n")

    with pytest.raises(policy.CorpusPrivacyError, match="validation failed"):
        policy.authenticate_worktree_safety_corpus(tmp_path)


def test_worktree_authentication_rejects_reparse_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = _write_corpus(tmp_path)
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
    _git(tmp_path, "add", "--", policy.SAFETY_CORPUS_RELATIVE.as_posix())

    authenticated = policy.authenticate_index_safety_corpus(tmp_path)

    assert len(authenticated.members) == len(_MEMBER_BYTES) + 1


def test_index_authentication_rejects_partial_staging(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write_corpus(tmp_path)
    one_member = policy.SAFETY_CORPUS_RELATIVE / "pngs" / "tc-000000.png"
    _git(tmp_path, "add", "--", one_member.as_posix())

    with pytest.raises(policy.CorpusPrivacyError, match="worktree differs"):
        policy.authenticate_index_safety_corpus(tmp_path)


def test_index_authentication_rejects_untracked_worktree_extra(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    corpus = _write_corpus(tmp_path)
    _git(tmp_path, "add", "--", policy.SAFETY_CORPUS_RELATIVE.as_posix())
    (corpus / "extra.png").write_bytes(b"extra")

    with pytest.raises(policy.CorpusPrivacyError, match="worktree differs"):
        policy.authenticate_index_safety_corpus(tmp_path)


def test_index_authentication_rejects_worktree_bytes_different_from_index(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    corpus = _write_corpus(tmp_path)
    _git(tmp_path, "add", "--", policy.SAFETY_CORPUS_RELATIVE.as_posix())
    (corpus / "pngs" / "tc-000000.png").write_bytes(b"unstaged replacement")

    with pytest.raises(policy.CorpusPrivacyError, match="worktree differs"):
        policy.authenticate_index_safety_corpus(tmp_path)


def test_index_authentication_rejects_symlink_mode(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _write_corpus(tmp_path)
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
