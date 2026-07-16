"""Create one authenticated Tier C v2 release freeze without overwrite.

Dataset generation never calls this module.  A maintainer must invoke it with
``--write`` after generating and independently verifying the canonical dataset.
Existing bytes are accepted only when they are identical.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from data.generators.occurrences import Split
from data.generators.tier_c import CANONICAL_DATASETS
from data.tier_c_contract import (
    TierCContractError,
    canonical_manifest_bytes,
    default_frozen_manifest_path,
    load_verified_canonical_split,
)
from src.paths import REPO_ROOT

DEFAULT_TIER_C_DIR = REPO_ROOT / "data" / "synthetic" / "tier_c"


def _persist_once(destination: Path, content: bytes) -> str:
    """Create *destination* atomically; never replace different existing bytes."""
    if destination.exists():
        if destination.read_bytes() != content:
            raise TierCContractError(f"RECUSADO: freeze existente diverge: {destination}")
        return "verified"

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("xb") as handle:
            handle.write(content)
    except FileExistsError:
        if destination.read_bytes() != content:
            raise TierCContractError(
                f"RECUSADO: freeze concorrente diverge: {destination}"
            ) from None
        return "verified"
    return "created"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Freeze an authenticated Tier C v2 manifest.")
    parser.add_argument("--dir", type=Path, default=DEFAULT_TIER_C_DIR)
    parser.add_argument("--dataset", choices=sorted(CANONICAL_DATASETS), required=True)
    parser.add_argument("--split", choices=["train", "val", "test"], required=True)
    parser.add_argument(
        "--write",
        action="store_true",
        required=True,
        help="explicitly authorize creation of the missing read-only freeze",
    )
    args = parser.parse_args(argv)
    split: Split = args.split

    destination = default_frozen_manifest_path(args.dataset, split)
    if destination is None:
        print(
            f"RECUSADO: dataset={args.dataset} split={split} não é um gate congelado",
            file=sys.stderr,
        )
        return 1

    local_manifest = args.dir / "manifests" / f"{split}.jsonl"
    try:
        verified = load_verified_canonical_split(
            args.dir,
            args.dataset,
            split,
            frozen_path=local_manifest,
        )
        outcome = _persist_once(destination, canonical_manifest_bytes(verified.entries))
    except (OSError, TierCContractError) as exc:
        print(f"CONTRATO TIER C INVÁLIDO: {exc}", file=sys.stderr)
        return 1

    print(
        f"Tier C v2 freeze {outcome}: dataset={args.dataset} split={split} "
        f"sha256={verified.manifest_sha256} path={destination}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
