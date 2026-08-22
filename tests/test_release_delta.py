"""Release promotion changes only authenticated evidence and its public narrative."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

import scripts.verify_release_delta as release_delta
from scripts.verify_release_delta import (
    CATALOG_SCHEMA,
    RELEASE_CATALOG,
    RELEASE_CATALOG_ID,
    RELEASE_EVIDENCE,
    RELEASE_NARRATIVE,
    ReleaseDeltaError,
    verify_release_delta,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _write(repo: Path, path: Path, content: str) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="\n")


def _repository(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "release-repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Release Test")
    _git(repo, "config", "user.email", "release@example.invalid")
    _write(repo, Path("src/app.py"), "VERSION = '1.1.0'\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "candidate")
    return repo, _git(repo, "rev-parse", "HEAD")


def _promote(repo: Path, candidate: str, *, extra_path: Path | None = None) -> None:
    evidence = json.dumps({"run": {"git_commit": candidate}}, sort_keys=True) + "\n"
    evidence_bytes = evidence.encode("utf-8")
    _write(repo, RELEASE_EVIDENCE, evidence)
    catalog = {
        "artifacts": [
            {
                "id": RELEASE_CATALOG_ID,
                "path": RELEASE_EVIDENCE.as_posix(),
                "run_commit": candidate,
                "sha256": hashlib.sha256(evidence_bytes).hexdigest(),
                "bytes": len(evidence_bytes),
                "kind": "result",
                "status": "current_release",
                "release_blocking": True,
                "limitations": [],
            }
        ],
        "schema": CATALOG_SCHEMA,
    }
    _write(repo, RELEASE_CATALOG, json.dumps(catalog, sort_keys=True) + "\n")
    evidence_link = RELEASE_EVIDENCE.relative_to(RELEASE_NARRATIVE.parent).as_posix()
    narrative = (
        f"# Validated v1.1 release evidence\n\n[{evidence_link}]({evidence_link})\n\n{candidate}\n"
    )
    _write(repo, RELEASE_NARRATIVE, narrative)
    if extra_path is not None:
        _write(repo, extra_path, "unexpected\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "docs(eval): publish validated release evidence")


def test_non_promotion_commit_is_ignored(tmp_path: Path) -> None:
    repo, candidate = _repository(tmp_path)
    _write(repo, Path("README.md"), "portfolio\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "docs: update readme")

    assert verify_release_delta(repo, base=candidate, head="HEAD") == "not-promoted"


def test_exact_evidence_promotion_is_accepted(tmp_path: Path) -> None:
    repo, candidate = _repository(tmp_path)
    _promote(repo, candidate)

    assert verify_release_delta(repo, base=candidate, head="HEAD") == "promotion"


def test_later_commit_preserves_published_evidence_identity(tmp_path: Path) -> None:
    repo, candidate = _repository(tmp_path)
    _promote(repo, candidate)
    promoted = _git(repo, "rev-parse", "HEAD")
    _write(repo, Path("README.md"), "post-release maintenance\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "docs: maintain readme")

    assert verify_release_delta(repo, base=promoted, head="HEAD") == "not-promoted"


def test_promotion_rejects_source_changes(tmp_path: Path) -> None:
    repo, candidate = _repository(tmp_path)
    _promote(repo, candidate, extra_path=Path("src/app.py"))

    with pytest.raises(ReleaseDeltaError, match="non-release changes"):
        verify_release_delta(repo, base=candidate, head="HEAD")


def test_promotion_rejects_evidence_for_another_commit(tmp_path: Path) -> None:
    repo, candidate = _repository(tmp_path)
    _promote(repo, candidate)
    evidence = {"run": {"git_commit": "0" * 40}}
    _write(repo, RELEASE_EVIDENCE, json.dumps(evidence) + "\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "--amend", "--no-edit")

    with pytest.raises(ReleaseDeltaError, match="parent candidate"):
        verify_release_delta(repo, base=candidate, head="HEAD")


def test_promotion_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    repo, candidate = _repository(tmp_path)
    _promote(repo, candidate)
    duplicate = f'{{"run": {{"git_commit": "{candidate}", "git_commit": "{candidate}"}}}}\n'
    _write(repo, RELEASE_EVIDENCE, duplicate)
    _git(repo, "add", ".")
    _git(repo, "commit", "--amend", "--no-edit")

    with pytest.raises(ReleaseDeltaError, match="duplicate JSON keys"):
        verify_release_delta(repo, base=candidate, head="HEAD")


def test_promotion_requires_narrative_identity(tmp_path: Path) -> None:
    repo, candidate = _repository(tmp_path)
    _promote(repo, candidate)
    _write(repo, RELEASE_NARRATIVE, "# Unbound narrative\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "--amend", "--no-edit")

    with pytest.raises(ReleaseDeltaError, match="not bound"):
        verify_release_delta(repo, base=candidate, head="HEAD")


def test_promotion_requires_catalog_and_narrative_changes(tmp_path: Path) -> None:
    repo, candidate = _repository(tmp_path)
    evidence = json.dumps({"run": {"git_commit": candidate}}, sort_keys=True) + "\n"
    _write(repo, RELEASE_EVIDENCE, evidence)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "incomplete promotion")

    with pytest.raises(ReleaseDeltaError, match="missing required release files"):
        verify_release_delta(repo, base=candidate, head="HEAD")


def test_published_evidence_remains_write_once(tmp_path: Path) -> None:
    repo, candidate = _repository(tmp_path)
    _promote(repo, candidate)
    promoted = _git(repo, "rev-parse", "HEAD")
    replacement = {"artifact_schema": "tampered", "run": {"git_commit": candidate}}
    _write(repo, RELEASE_EVIDENCE, json.dumps(replacement) + "\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "rewrite evidence")

    with pytest.raises(ReleaseDeltaError, match="write-once"):
        verify_release_delta(repo, base=promoted, head="HEAD")


def test_published_evidence_cannot_be_unlinked_from_catalog(tmp_path: Path) -> None:
    repo, candidate = _repository(tmp_path)
    _promote(repo, candidate)
    promoted = _git(repo, "rev-parse", "HEAD")
    _write(repo, RELEASE_CATALOG, json.dumps({"schema": CATALOG_SCHEMA, "artifacts": []}) + "\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "unlink evidence")

    with pytest.raises(ReleaseDeltaError, match="exactly one current release"):
        verify_release_delta(repo, base=promoted, head="HEAD")


def test_published_evidence_cannot_be_deleted(tmp_path: Path) -> None:
    repo, candidate = _repository(tmp_path)
    _promote(repo, candidate)
    promoted = _git(repo, "rev-parse", "HEAD")
    (repo / RELEASE_EVIDENCE).unlink()
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "delete evidence")

    with pytest.raises(ReleaseDeltaError, match="was deleted"):
        verify_release_delta(repo, base=promoted, head="HEAD")


def test_cli_can_require_the_exact_promotion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, candidate = _repository(tmp_path)
    monkeypatch.setattr(release_delta, "REPO_ROOT", repo)

    assert (
        release_delta.main(["--base", candidate, "--head", candidate, "--require-promotion"]) == 1
    )

    _promote(repo, candidate)
    assert release_delta.main(["--base", candidate, "--head", "HEAD", "--require-promotion"]) == 0
