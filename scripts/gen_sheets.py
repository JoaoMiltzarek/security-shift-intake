"""CLI de `make gen-sheets` — folhas sintéticas Tier C ("Controle de ocorrências").

Usage:
    uv run --locked python -m scripts.gen_sheets --dataset smoke
    uv run --locked python -m scripts.gen_sheets --seed 42 --n 12 --profile balanced
    uv run --locked python -m scripts.gen_sheets --dataset smoke --n-samples 2

Escreve PDFs + PNGs + gt/*.json + manifests {train,val,test}.jsonl + meta.json em
--out (gitignored). Generation never creates or updates the committed release freeze.
After independent verification, the explicit write-once maintainer action is
`uv run --locked python -m scripts.freeze_tier_c_manifest ... --write`
(docs/DATASET_CONTRACT.md §3–§4).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from data.generators.tier_c import CANONICAL_DATASETS, build_tier_c


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Generate Tier C occurrence-table sheets.")
    parser.add_argument("--dataset", choices=sorted(CANONICAL_DATASETS), default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n", type=int, default=50)
    parser.add_argument("--profile", choices=["balanced", "operational"], default="balanced")
    parser.add_argument("--split-seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=Path("data/synthetic/tier_c"))
    parser.add_argument("--samples", type=Path, default=Path("samples"))
    parser.add_argument("--n-samples", type=int, default=0)
    args = parser.parse_args(argv)

    meta = build_tier_c(
        out_dir=args.out,
        dataset=args.dataset,
        seed=args.seed,
        n=args.n,
        profile=args.profile,
        split_seed=args.split_seed,
        n_samples=args.n_samples,
        samples_dir=args.samples,
    )

    print(
        f"Wrote {meta.n} sheets to {args.out} (dataset={meta.dataset}, "
        f"version={meta.version}, seed={meta.seed}, profile={meta.profile})"
    )
    for name, count in meta.counts.items():
        print(f"  {name}: {count}")
    if args.n_samples > 0:
        print(f"Samples ({args.n_samples}) -> {args.samples}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
