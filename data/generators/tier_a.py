"""Tier A dataset assembly: generate many records, split without leakage, persist.

This is the orchestration layer over data/generators/records.py:
  generate_dataset -> split_dataset (disjoint) -> write_dataset (JSONL + meta)

Everything is seeded and reproducible. The split holds out distinct record draws
(disjoint record_ids), so no record appears in two splits — verified by tests.
"""

from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path

from pydantic import BaseModel

from data.generators.records import SyntheticRecord, generate_record

DATASET_VERSION = "tier_a/v1"
DEFAULT_SPLIT_RATIOS = (0.70, 0.15, 0.15)  # train, val, test


class DatasetMeta(BaseModel):
    """Reproducibility metadata written alongside the dataset."""

    version: str
    seed: int
    n: int
    split_seed: int
    split_ratios: tuple[float, float, float]
    counts: dict[str, int]


def generate_dataset(seed: int, n: int) -> list[SyntheticRecord]:
    """Generate *n* seeded records with stable, zero-padded record ids."""
    if n <= 0:
        raise ValueError("n must be positive")
    rng = random.Random(seed)
    return [generate_record(rng, f"rec-{i:06d}") for i in range(n)]


def split_dataset(
    records: list[SyntheticRecord],
    ratios: tuple[float, float, float] = DEFAULT_SPLIT_RATIOS,
    split_seed: int = 0,
) -> dict[str, list[SyntheticRecord]]:
    """Partition records into disjoint train/val/test splits (no leakage)."""
    if abs(sum(ratios) - 1.0) > 1e-6:
        raise ValueError(f"split ratios must sum to 1, got {ratios}")

    shuffled = list(records)
    random.Random(split_seed).shuffle(shuffled)

    n = len(shuffled)
    n_train = int(n * ratios[0])
    n_val = int(n * ratios[1])
    return {
        "train": shuffled[:n_train],
        "val": shuffled[n_train : n_train + n_val],
        "test": shuffled[n_train + n_val :],
    }


def write_dataset(
    out_dir: Path,
    splits: dict[str, list[SyntheticRecord]],
    meta: DatasetMeta,
) -> None:
    """Write one JSONL file per split plus meta.json into *out_dir*."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, records in splits.items():
        path = out_dir / f"{name}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec.model_dump(mode="json"), ensure_ascii=False))
                fh.write("\n")
    (out_dir / "meta.json").write_text(
        json.dumps(meta.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_and_write(
    out_dir: Path,
    seed: int,
    n: int,
    split_seed: int = 0,
    ratios: tuple[float, float, float] = DEFAULT_SPLIT_RATIOS,
) -> DatasetMeta:
    """End-to-end: generate, split, write. Returns the metadata written."""
    records = generate_dataset(seed=seed, n=n)
    splits = split_dataset(records, ratios=ratios, split_seed=split_seed)
    counts = {name: len(recs) for name, recs in splits.items()}
    meta = DatasetMeta(
        version=DATASET_VERSION,
        seed=seed,
        n=n,
        split_seed=split_seed,
        split_ratios=ratios,
        counts=counts,
    )
    write_dataset(out_dir, splits, meta)
    return meta


def incident_rate(records: list[SyntheticRecord]) -> float:
    """Fraction of records with an incident (helper for distribution checks)."""
    if not records:
        return 0.0
    return sum(1 for r in records if r.incident_occurred) / len(records)


def type_counts(records: list[SyntheticRecord]) -> Counter[str]:
    return Counter(r.incident_type for r in records)
