"""Verify that an evidence-promotion commit changes only the approved release surface.

The CI job runs the full evidence-schema validator immediately before this delta check. This
module independently binds the immutable artifact, catalog identity, narrative, and measured
parent commit. A later release must version these constants before superseding v1.1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn, cast

from src.paths import REPO_ROOT

CATALOG_SCHEMA = "ssi-eval-artifact-catalog/v1"
RELEASE_EVIDENCE = Path(
    "docs/evals/releases/v1.1.0/eval-safety.bench-balanced.val.local_ocr.dpi150.json"
)
RELEASE_CATALOG = Path("docs/evals/catalog.json")
RELEASE_NARRATIVE = Path("docs/EVAL_RELEASE.md")
RELEASE_CATALOG_ID = "v1.1.0-eval-safety-bench-balanced-val-local-ocr-dpi150"
ALLOWED_PROMOTION_PATHS = frozenset({RELEASE_EVIDENCE, RELEASE_CATALOG, RELEASE_NARRATIVE})


class ReleaseDeltaError(RuntimeError):
    """The proposed release-evidence delta is not the allowed promotion commit."""


def _git(repo: Path, *args: str, text: bool = False) -> bytes | str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=text,
    )
    return cast(bytes | str, result.stdout)


def _commit(repo: Path, revision: str) -> str:
    output = _git(repo, "rev-parse", "--verify", f"{revision}^{{commit}}", text=True)
    assert isinstance(output, str)
    return output.strip()


def _blob(repo: Path, revision: str, path: Path) -> bytes | None:
    spec = f"{revision}:{path.as_posix()}"
    exists = subprocess.run(
        ["git", "cat-file", "-e", spec],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if exists.returncode != 0:
        return None
    content = _git(repo, "cat-file", "blob", spec)
    assert isinstance(content, bytes)
    return content


def _json_object(content: bytes, *, label: str) -> dict[str, Any]:
    def reject_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ReleaseDeltaError(f"{label} contains duplicate JSON keys")
            value[key] = item
        return value

    def reject_constant(value: str) -> NoReturn:
        raise ReleaseDeltaError(f"{label} contains non-finite JSON value {value}")

    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=reject_pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseDeltaError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ReleaseDeltaError(f"{label} must contain a JSON object")
    return value


def _changed_paths(repo: Path, base: str, head: str) -> set[Path]:
    output = _git(repo, "diff", "--name-only", "-z", base, head, "--")
    assert isinstance(output, bytes)
    try:
        return {Path(item.decode("utf-8")) for item in output.split(b"\0") if item}
    except UnicodeDecodeError as exc:
        raise ReleaseDeltaError("release delta contains a non-UTF-8 path") from exc


def _verify_catalog_identity(
    repo: Path,
    *,
    revision: str,
    evidence: bytes,
    measured_commit: str,
) -> None:
    catalog_content = _blob(repo, revision, RELEASE_CATALOG)
    if catalog_content is None:
        raise ReleaseDeltaError("release catalog is missing")
    catalog = _json_object(catalog_content, label="release catalog")
    if catalog.get("schema") != CATALOG_SCHEMA:
        raise ReleaseDeltaError("release catalog schema is invalid")
    entries = catalog.get("artifacts")
    if not isinstance(entries, list):
        raise ReleaseDeltaError("release catalog artifacts must be a list")
    current = [
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("status") == "current_release"
    ]
    if len(current) != 1:
        raise ReleaseDeltaError("release catalog must contain exactly one current release")
    expected_identity = {
        "id": RELEASE_CATALOG_ID,
        "path": RELEASE_EVIDENCE.as_posix(),
        "sha256": hashlib.sha256(evidence).hexdigest(),
        "bytes": len(evidence),
        "kind": "result",
        "status": "current_release",
        "release_blocking": True,
        "run_commit": measured_commit,
        "limitations": [],
    }
    if current[0] != expected_identity:
        raise ReleaseDeltaError("release catalog identity does not match the promoted evidence")


def _verify_narrative_identity(repo: Path, *, revision: str, measured_commit: str) -> None:
    content = _blob(repo, revision, RELEASE_NARRATIVE)
    if content is None:
        raise ReleaseDeltaError("release narrative is missing")
    try:
        narrative = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseDeltaError("release narrative is not valid UTF-8") from exc
    evidence_link = RELEASE_EVIDENCE.relative_to(RELEASE_NARRATIVE.parent).as_posix()
    if evidence_link not in narrative or measured_commit not in narrative:
        raise ReleaseDeltaError(
            "release narrative is not bound to the evidence and measured commit"
        )


def verify_release_delta(repo: Path, *, base: str, head: str) -> str:
    """Return ``promotion`` or ``not-promoted``; raise on a forbidden release delta."""
    repo = repo.resolve(strict=True)
    base_commit = _commit(repo, base)
    head_commit = _commit(repo, head)
    base_evidence = _blob(repo, base_commit, RELEASE_EVIDENCE)
    head_evidence = _blob(repo, head_commit, RELEASE_EVIDENCE)
    changed = _changed_paths(repo, base_commit, head_commit)

    if head_evidence is None:
        if RELEASE_EVIDENCE in changed:
            raise ReleaseDeltaError("the v1.1 release evidence was deleted")
        return "not-promoted"
    payload = _json_object(head_evidence, label="release evidence")
    run = payload.get("run")
    measured_commit = run.get("git_commit") if isinstance(run, dict) else None
    if (
        not isinstance(measured_commit, str)
        or re.fullmatch(r"[0-9a-f]{40}", measured_commit) is None
    ):
        raise ReleaseDeltaError("release evidence has no valid measured commit")
    if base_evidence is not None:
        if RELEASE_EVIDENCE in changed:
            raise ReleaseDeltaError("the write-once v1.1 release evidence was modified")
        _verify_catalog_identity(
            repo,
            revision=head_commit,
            evidence=head_evidence,
            measured_commit=measured_commit,
        )
        _verify_narrative_identity(repo, revision=head_commit, measured_commit=measured_commit)
        return "not-promoted"

    unexpected = changed - ALLOWED_PROMOTION_PATHS
    if unexpected:
        names = ", ".join(path.as_posix() for path in sorted(unexpected, key=str))
        raise ReleaseDeltaError(f"promotion contains non-release changes: {names}")
    required = {RELEASE_EVIDENCE, RELEASE_CATALOG, RELEASE_NARRATIVE}
    missing = required - changed
    if missing:
        names = ", ".join(path.as_posix() for path in sorted(missing, key=str))
        raise ReleaseDeltaError(f"promotion is missing required release files: {names}")

    if measured_commit != base_commit:
        raise ReleaseDeltaError("release evidence does not measure the parent candidate commit")
    _verify_catalog_identity(
        repo,
        revision=head_commit,
        evidence=head_evidence,
        measured_commit=base_commit,
    )
    _verify_narrative_identity(repo, revision=head_commit, measured_commit=base_commit)
    return "promotion"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="HEAD^")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args(argv)
    try:
        outcome = verify_release_delta(REPO_ROOT, base=args.base, head=args.head)
    except (OSError, subprocess.SubprocessError, ReleaseDeltaError) as exc:
        print(f"Release delta invalid: {exc}", file=sys.stderr)
        return 1
    print(f"Release delta check: {outcome}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
