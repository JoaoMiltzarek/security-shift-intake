"""CLI entry point for `make gen-data` — Tier A synthetic records.

Usage:
    python scripts/gen_data.py [--seed 42] [--n 1000] [--out data/synthetic]

Writes train/val/test JSONL + meta.json. Fully reproducible from the seed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from data.generators.tier_a import build_and_write


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Generate Tier A synthetic records.")
    parser.add_argument("--seed", type=int, default=42, help="generation seed")
    parser.add_argument("--n", type=int, default=1000, help="number of records")
    parser.add_argument("--split-seed", type=int, default=0, help="split shuffle seed")
    parser.add_argument("--out", type=Path, default=Path("data/synthetic"), help="output dir")
    args = parser.parse_args(argv)

    meta = build_and_write(out_dir=args.out, seed=args.seed, n=args.n, split_seed=args.split_seed)

    print(f"Wrote {args.n} records to {args.out} (version={meta.version}, seed={meta.seed})")
    for name, count in meta.counts.items():
        print(f"  {name}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
