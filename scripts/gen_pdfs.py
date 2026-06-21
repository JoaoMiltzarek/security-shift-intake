"""CLI entry point for `make gen-pdfs` — Tier B handwritten-form PDFs.

Usage:
    python scripts/gen_pdfs.py [--seed 42] [--n 20] [--dpi 200]
                               [--out data/synthetic/tier_b]
                               [--samples samples] [--n-samples 2]

Writes PDFs + ground_truth.jsonl to --out, and a few PNG samples (for eyeballing,
committed to the repo) to --samples. Fully reproducible from the seed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from data.generators.tier_b import build_tier_b


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Generate Tier B handwritten-form PDFs.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n", type=int, default=20)
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--out", type=Path, default=Path("data/synthetic/tier_b"))
    parser.add_argument("--samples", type=Path, default=Path("samples"))
    parser.add_argument("--n-samples", type=int, default=2)
    args = parser.parse_args(argv)

    meta = build_tier_b(
        out_dir=args.out,
        seed=args.seed,
        n=args.n,
        dpi=args.dpi,
        n_samples=args.n_samples,
        samples_dir=args.samples,
    )

    print(f"Wrote {meta.n} PDFs to {args.out / 'pdfs'} (version={meta.version}, dpi={meta.dpi})")
    print(f"Ground truth: {args.out / 'ground_truth.jsonl'}")
    if args.n_samples > 0:
        print(f"Samples ({args.n_samples}) -> {args.samples}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
