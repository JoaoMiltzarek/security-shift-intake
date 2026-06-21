"""M2.d (DoD): the dataset's distribution is honest — non-uniform, joint-respecting.

This is the milestone's headline test: it proves the generator encodes the
documented priors rather than uniform-random noise.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from data.generators import priors
from data.generators.records import SyntheticRecord
from data.generators.tier_a import (
    DEFAULT_SPLIT_RATIOS,
    build_and_write,
    generate_dataset,
    incident_rate,
    split_dataset,
    type_counts,
)

# Expected overall incident rate, derived from the documented priors:
#   sum_s P(shift=s) * P(incident | s)
_EXPECTED_INCIDENT_RATE = sum(
    priors.P_SHIFT_PERIOD[s] * priors.P_INCIDENT_GIVEN_SHIFT[s] for s in priors.SHIFT_PERIODS
)


@pytest.fixture(scope="module")
def dataset() -> list[SyntheticRecord]:
    return generate_dataset(seed=42, n=6000)


# ---------------------------------------------------------------------------
# Marginal: incident rate matches the prior (~0.30, NOT 0.5)
# ---------------------------------------------------------------------------


def test_incident_rate_matches_prior(dataset: list[SyntheticRecord]) -> None:
    rate = incident_rate(dataset)
    assert abs(rate - _EXPECTED_INCIDENT_RATE) < 0.03
    # And it is clearly not a coin flip (uniform would be ~0.5).
    assert rate < 0.40


def test_majority_of_shifts_are_routine(dataset: list[SyntheticRecord]) -> None:
    routine = sum(1 for r in dataset if r.incident_type == "routine")
    assert routine / len(dataset) > 0.60  # ~70% routine per the prior


# ---------------------------------------------------------------------------
# Type distribution is SKEWED (not uniform across incident types)
# ---------------------------------------------------------------------------


def test_incident_types_are_skewed(dataset: list[SyntheticRecord]) -> None:
    counts = type_counts(dataset)
    # Among real incidents, access_violation should dominate "other".
    assert counts["access_violation"] > counts["other"] * 2
    # The non-routine types are far from uniform.
    incident_types = [t for t in priors.TYPE_LABELS if t != "routine"]
    freqs = [counts[t] for t in incident_types]
    assert max(freqs) > min(freqs) * 2


# ---------------------------------------------------------------------------
# Joint: urgency | type is respected (conditional, not independent)
# ---------------------------------------------------------------------------


def test_safety_rarely_low_urgency(dataset: list[SyntheticRecord]) -> None:
    safety = [r for r in dataset if r.incident_type == "safety"]
    assert len(safety) > 50
    low = sum(1 for r in safety if r.urgency == "low")
    # Prior says P(low|safety)=0.05 — empirically should stay well under 0.15.
    assert low / len(safety) < 0.15


def test_routine_is_always_low(dataset: list[SyntheticRecord]) -> None:
    routine = [r for r in dataset if r.incident_type == "routine"]
    assert all(r.urgency == "low" for r in routine)


def test_no_sampled_urgency_has_zero_prior(dataset: list[SyntheticRecord]) -> None:
    for r in dataset:
        assert priors.P_URGENCY_GIVEN_TYPE[r.incident_type][r.urgency] > 0.0


# ---------------------------------------------------------------------------
# Temporal: night shifts have a higher empirical incident rate than day
# ---------------------------------------------------------------------------


def test_night_incident_rate_higher_than_day(dataset: list[SyntheticRecord]) -> None:
    day = [r for r in dataset if r.shift_period == "day"]
    night = [r for r in dataset if r.shift_period == "night"]
    assert incident_rate(night) > incident_rate(day)


# ---------------------------------------------------------------------------
# Split has NO leakage and correct proportions
# ---------------------------------------------------------------------------


def test_split_no_leakage(dataset: list[SyntheticRecord]) -> None:
    splits = split_dataset(dataset, ratios=DEFAULT_SPLIT_RATIOS, split_seed=0)
    ids_train = {r.record_id for r in splits["train"]}
    ids_val = {r.record_id for r in splits["val"]}
    ids_test = {r.record_id for r in splits["test"]}
    # Pairwise disjoint.
    assert ids_train.isdisjoint(ids_val)
    assert ids_train.isdisjoint(ids_test)
    assert ids_val.isdisjoint(ids_test)
    # Union covers everything exactly once.
    assert len(ids_train) + len(ids_val) + len(ids_test) == len(dataset)
    assert ids_train | ids_val | ids_test == {r.record_id for r in dataset}


def test_split_proportions(dataset: list[SyntheticRecord]) -> None:
    splits = split_dataset(dataset, ratios=DEFAULT_SPLIT_RATIOS, split_seed=0)
    n = len(dataset)
    assert abs(len(splits["train"]) / n - 0.70) < 0.02
    assert abs(len(splits["val"]) / n - 0.15) < 0.02
    assert abs(len(splits["test"]) / n - 0.15) < 0.02


def test_split_is_deterministic(dataset: list[SyntheticRecord]) -> None:
    a = split_dataset(dataset, split_seed=0)
    b = split_dataset(dataset, split_seed=0)
    assert [r.record_id for r in a["train"]] == [r.record_id for r in b["train"]]


# ---------------------------------------------------------------------------
# Integration: build_and_write produces valid, reloadable artifacts
# ---------------------------------------------------------------------------


def test_build_and_write_creates_artifacts(tmp_path: Path) -> None:
    meta = build_and_write(out_dir=tmp_path, seed=7, n=200)
    assert (tmp_path / "train.jsonl").exists()
    assert (tmp_path / "val.jsonl").exists()
    assert (tmp_path / "test.jsonl").exists()
    assert (tmp_path / "meta.json").exists()
    assert sum(meta.counts.values()) == 200

    # Records round-trip back into the model.
    lines = (tmp_path / "train.jsonl").read_text(encoding="utf-8").splitlines()
    rec = SyntheticRecord.model_validate_json(lines[0])
    assert rec.record_id.startswith("rec-")

    loaded_meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert loaded_meta["seed"] == 7
    assert loaded_meta["version"] == "tier_a/v1"
