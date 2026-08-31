"""Verify the downloaded corpus-and-pin checkpoint before repository import."""

from __future__ import annotations

import argparse
import stat
import subprocess
import sys
from pathlib import Path

from data.safety_corpus import (
    SAFETY_CORPUS_PIN_RELATIVE,
    SAFETY_COUNT,
    VerifiedSafetyCorpus,
    load_verified_safety_corpus,
)
from data.tier_c_contract import SAFETY_LOGICAL_FREEZE, TierCContractError
from src.paths import REPO_ROOT

CORPUS_MEMBER = "corpus"
PIN_MEMBER = SAFETY_CORPUS_PIN_RELATIVE.name


def _is_redirected(path: Path) -> bool:
    metadata = path.lstat()
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & reparse_flag)


def _plain_checkpoint(root: Path) -> tuple[Path, Path]:
    try:
        metadata = root.lstat()
        members = list(root.iterdir())
    except OSError as exc:
        raise TierCContractError("safety corpus checkpoint is unavailable") from exc
    if _is_redirected(root) or not stat.S_ISDIR(metadata.st_mode):
        raise TierCContractError("safety corpus checkpoint root must be a plain directory")
    if {member.name for member in members} != {CORPUS_MEMBER, PIN_MEMBER}:
        raise TierCContractError("safety corpus checkpoint members are not exact")
    corpus = root / CORPUS_MEMBER
    pin = root / PIN_MEMBER
    try:
        corpus_metadata = corpus.lstat()
        pin_metadata = pin.lstat()
    except OSError as exc:
        raise TierCContractError("safety corpus checkpoint member is unreadable") from exc
    if _is_redirected(corpus) or not stat.S_ISDIR(corpus_metadata.st_mode):
        raise TierCContractError("checkpoint corpus must be a plain directory")
    if _is_redirected(pin) or not stat.S_ISREG(pin_metadata.st_mode):
        raise TierCContractError("checkpoint inventory pin must be a plain file")
    return corpus, pin


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
    except (OSError, subprocess.SubprocessError) as exc:
        raise TierCContractError("checkpoint verifier cannot identify Git HEAD") from exc
    return completed.stdout.strip()


def verify_checkpoint(root: Path) -> VerifiedSafetyCorpus:
    """Authenticate one exact builder artifact against its generator checkout."""
    checkpoint = root.expanduser().absolute()
    corpus, pin = _plain_checkpoint(checkpoint)
    verified = load_verified_safety_corpus(
        corpus,
        pin_path=pin,
        logical_freeze_path=SAFETY_LOGICAL_FREEZE,
    )
    if len(verified.split.entries) != SAFETY_COUNT:
        raise TierCContractError(
            f"safety corpus checkpoint has {len(verified.split.entries)} sheets, "
            f"expected {SAFETY_COUNT}"
        )
    if verified.provenance.generator_commit != _git_commit():
        raise TierCContractError("safety corpus checkpoint commit differs from this checkout")
    return verified


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Verify a downloaded v1.1 corpus checkpoint before import."
    )
    parser.add_argument("--checkpoint", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        verified = verify_checkpoint(args.checkpoint)
    except (OSError, TierCContractError, ValueError) as exc:
        print(f"SAFETY CORPUS CHECKPOINT REFUSED: {exc}", file=sys.stderr)
        return 1
    print(
        f"Safety corpus checkpoint verified: sheets={len(verified.split.entries)}, "
        f"logical_freeze={verified.provenance.logical_freeze_sha256}, "
        f"manifest={verified.provenance.manifest_sha256}, "
        f"commit={verified.provenance.generator_commit}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
