"""Documented priors for synthetic occurrence-table sheets.

The distributions are deliberately non-uniform and contain no real identities or
observations. They model only the canonical Tier C corpus used by safety evaluation.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

Distribution = dict[str, float]

P_SHIFT_PERIOD: Distribution = {"day": 0.52, "night": 0.48}

GUARD_NAMES = [
    "A. Souza",
    "B. Lima",
    "C. Pereira",
    "D. Oliveira",
    "E. Costa",
    "F. Almeida",
    "G. Rocha",
    "H. Martins",
    "I. Barbosa",
    "J. Ferreira",
    "K. Gomes",
    "L. Ribeiro",
    "M. Carvalho",
    "N. Teixeira",
    "O. Dias",
]

P_SA_GIVEN_PROFILE: dict[str, float] = {"balanced": 0.50, "operational": 0.70}
P_RISCADO_GIVEN_NO_OCCURRENCE = 0.25
P_N_OCORRENCIAS_GIVEN_OCCURRENCE: dict[int, float] = {1: 0.55, 2: 0.30, 3: 0.15}
P_N_VIGILANTES: dict[int, float] = {1: 0.35, 2: 0.45, 3: 0.20}
P_HORA_DUPLA = 0.30
P_RESOLVIDO: Distribution = {"sim": 0.60, "nao": 0.25, "em_branco": 0.15}

UNIDADES = [
    "Unidade 01",
    "Unidade 02",
    "Unidade 03",
    "Unidade 05",
    "Unidade 07",
    "Unidade 09",
    "Unidade 12",
    "Posto Delta",
    "Posto Horizonte",
    "Posto Mirante",
]


def is_valid_distribution(distribution: Mapping[Any, float], tolerance: float = 1e-6) -> bool:
    """Return whether probabilities are non-negative and sum to one."""
    if not distribution or any(probability < 0 for probability in distribution.values()):
        return False
    return abs(sum(distribution.values()) - 1.0) <= tolerance


def validate_all_priors() -> None:
    """Raise when any occurrence-sheet prior violates its declared bounds."""
    distributions: dict[str, Mapping[Any, float]] = {
        "P_SHIFT_PERIOD": P_SHIFT_PERIOD,
        "P_RESOLVIDO": P_RESOLVIDO,
        "P_N_OCORRENCIAS_GIVEN_OCCURRENCE": P_N_OCORRENCIAS_GIVEN_OCCURRENCE,
        "P_N_VIGILANTES": P_N_VIGILANTES,
    }
    for name, distribution in distributions.items():
        if not is_valid_distribution(distribution):
            raise ValueError(f"{name} is not a valid distribution.")

    probabilities = {
        **{f"P_SA_GIVEN_PROFILE[{key!r}]": value for key, value in P_SA_GIVEN_PROFILE.items()},
        "P_RISCADO_GIVEN_NO_OCCURRENCE": P_RISCADO_GIVEN_NO_OCCURRENCE,
        "P_HORA_DUPLA": P_HORA_DUPLA,
    }
    for name, probability in probabilities.items():
        if not 0.0 <= probability <= 1.0:
            raise ValueError(f"{name} out of [0,1].")
