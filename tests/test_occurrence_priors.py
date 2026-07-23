"""Occurrence-sheet priors stay explicit and internally consistent."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from data.generators import occurrence_priors as priors


def test_all_occurrence_priors_validate() -> None:
    priors.validate_all_priors()


@pytest.mark.parametrize(
    "distribution",
    [
        priors.P_SHIFT_PERIOD,
        priors.P_RESOLVIDO,
        priors.P_N_OCORRENCIAS_GIVEN_OCCURRENCE,
        priors.P_N_VIGILANTES,
    ],
)
def test_occurrence_distributions_sum_to_one(distribution: Mapping[Any, float]) -> None:
    assert priors.is_valid_distribution(distribution)


def test_invalid_distributions_are_rejected() -> None:
    assert not priors.is_valid_distribution({})
    assert not priors.is_valid_distribution({"a": 0.8, "b": 0.3})
    assert not priors.is_valid_distribution({"a": 1.1, "b": -0.1})


def test_public_synthetic_identities_are_unique() -> None:
    assert len(priors.GUARD_NAMES) == len(set(priors.GUARD_NAMES))
    assert len(priors.UNIDADES) == len(set(priors.UNIDADES))
