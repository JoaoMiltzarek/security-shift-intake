"""M2.b: tests for the single-record generator (determinism, validity, consistency)."""

from __future__ import annotations

import random

from data.generators import priors
from data.generators.records import SyntheticRecord, generate_record


def _rng(seed: int = 42) -> random.Random:
    return random.Random(seed)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_same_seed_same_record() -> None:
    r1 = generate_record(_rng(123), "rec-0")
    r2 = generate_record(_rng(123), "rec-0")
    assert r1 == r2


def test_different_seed_can_differ() -> None:
    # Over a short sequence, two different seeds should produce at least one
    # differing record (guards against a constant generator).
    a = [generate_record(_rng(1), f"r{i}") for i in range(5)]
    rng_b = _rng(999)
    b = [generate_record(rng_b, f"r{i}") for i in range(5)]
    assert a != b


def test_sequence_from_one_rng_is_reproducible() -> None:
    rng_a = _rng(7)
    seq_a = [generate_record(rng_a, f"r{i}") for i in range(10)]
    rng_b = _rng(7)
    seq_b = [generate_record(rng_b, f"r{i}") for i in range(10)]
    assert seq_a == seq_b


# ---------------------------------------------------------------------------
# Validity — all sampled values are within the allowed vocabularies
# ---------------------------------------------------------------------------


def test_generated_values_are_valid() -> None:
    rng = _rng(2024)
    for i in range(200):
        rec = generate_record(rng, f"r{i}")
        assert isinstance(rec, SyntheticRecord)
        assert rec.shift_period in priors.SHIFT_PERIODS
        assert rec.incident_type in priors.TYPE_LABELS
        assert rec.urgency in priors.URGENCY_LABELS
        assert rec.sector in priors.SECTOR_LABELS
        assert rec.guard_name in priors.GUARD_NAMES
        assert rec.post in priors.POSTS


# ---------------------------------------------------------------------------
# Consistency — routine <=> no incident; urgency respects type constraints
# ---------------------------------------------------------------------------


def test_routine_iff_no_incident() -> None:
    rng = _rng(55)
    for i in range(500):
        rec = generate_record(rng, f"r{i}")
        if rec.incident_occurred:
            assert rec.incident_type != "routine"
        else:
            assert rec.incident_type == "routine"


def test_routine_always_low_urgency() -> None:
    rng = _rng(77)
    for i in range(500):
        rec = generate_record(rng, f"r{i}")
        if rec.incident_type == "routine":
            assert rec.urgency == "low"


def test_no_incident_has_no_description() -> None:
    rng = _rng(88)
    for i in range(300):
        rec = generate_record(rng, f"r{i}")
        if not rec.incident_occurred:
            assert rec.incident_description is None


def test_incident_has_description() -> None:
    rng = _rng(99)
    for i in range(300):
        rec = generate_record(rng, f"r{i}")
        if rec.incident_occurred:
            assert rec.incident_description is not None
            assert len(rec.incident_description) > 0


def test_urgency_respects_type_support() -> None:
    # A sampled urgency must have non-zero probability under its type's prior.
    rng = _rng(31)
    for i in range(500):
        rec = generate_record(rng, f"r{i}")
        assert priors.P_URGENCY_GIVEN_TYPE[rec.incident_type][rec.urgency] > 0.0
