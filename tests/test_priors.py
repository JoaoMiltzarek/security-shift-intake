"""M2.a: tests that the documented priors are well-formed and consistent.

These guard against the most common synthetic-data failure: dropping/breaking a
distribution so it no longer sums to 1, or drifting out of sync with the config
taxonomy.
"""

from __future__ import annotations

from pathlib import Path

from data.generators import priors
from src.schema.loader import load_config

CONFIG_PATH = Path("configs/htmicron_security.yaml")


# ---------------------------------------------------------------------------
# Distributions are well-formed
# ---------------------------------------------------------------------------


def test_validate_all_priors_passes() -> None:
    # Should not raise.
    priors.validate_all_priors()


def test_shift_period_distribution_sums_to_one() -> None:
    assert priors.is_valid_distribution(priors.P_SHIFT_PERIOD)


def test_type_given_incident_sums_to_one() -> None:
    assert priors.is_valid_distribution(priors.P_TYPE_GIVEN_INCIDENT)


def test_each_urgency_given_type_sums_to_one() -> None:
    for dist in priors.P_URGENCY_GIVEN_TYPE.values():
        assert priors.is_valid_distribution(dist)


def test_each_sector_given_type_sums_to_one() -> None:
    for dist in priors.P_SECTOR_GIVEN_TYPE.values():
        assert priors.is_valid_distribution(dist)


def test_incident_given_shift_in_range() -> None:
    for p in priors.P_INCIDENT_GIVEN_SHIFT.values():
        assert 0.0 <= p <= 1.0


# ---------------------------------------------------------------------------
# Priors are NON-uniform (the whole point — not a uniform-random shortcut)
# ---------------------------------------------------------------------------


def test_type_distribution_is_skewed_not_uniform() -> None:
    probs = list(priors.P_TYPE_GIVEN_INCIDENT.values())
    uniform = 1.0 / len(probs)
    # At least one type must deviate meaningfully from uniform.
    assert max(abs(p - uniform) for p in probs) > 0.10


def test_safety_is_never_low_dominant() -> None:
    # A safety event (e.g. fire alarm) must not skew "low".
    assert priors.P_URGENCY_GIVEN_TYPE["safety"]["low"] < 0.10


def test_night_shift_has_higher_incident_rate() -> None:
    assert priors.P_INCIDENT_GIVEN_SHIFT["night"] > priors.P_INCIDENT_GIVEN_SHIFT["day"]


# ---------------------------------------------------------------------------
# Consistency with the report config taxonomy
# ---------------------------------------------------------------------------


def test_type_labels_match_config() -> None:
    cfg = load_config(CONFIG_PATH)
    assert set(priors.TYPE_LABELS) == set(cfg.classification.type.labels)


def test_urgency_labels_match_config() -> None:
    cfg = load_config(CONFIG_PATH)
    assert set(priors.URGENCY_LABELS) == set(cfg.classification.urgency.labels)


def test_sector_labels_match_config() -> None:
    cfg = load_config(CONFIG_PATH)
    assert set(priors.SECTOR_LABELS) == set(cfg.classification.sector.labels)


def test_conditional_keys_cover_all_types() -> None:
    assert set(priors.P_URGENCY_GIVEN_TYPE.keys()) == set(priors.TYPE_LABELS)
    assert set(priors.P_SECTOR_GIVEN_TYPE.keys()) == set(priors.TYPE_LABELS)
