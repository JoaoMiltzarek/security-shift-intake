"""Tier A: generate a single synthetic shift-report record from documented priors.

The record IS the structured ground truth: clean field values plus the
classification labels (type / urgency / sector). Messiness (M2.c) is applied as a
separate surface layer so these clean labels are never lost.

Sampling preserves joint distributions (see data/generators/priors.py):
    shift_period -> incident|shift_period -> type|incident
                 -> urgency|type -> sector|type

Determinism: all randomness flows through a passed-in `random.Random` instance.
Same seed -> same records (proven by tests).
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from pydantic import BaseModel

from data.generators import priors

# Base epoch for shift dates (synthetic, fixed for reproducibility).
_EPOCH = date(2026, 1, 1)
_DATE_SPAN_DAYS = 365

# Shift start-hour windows (temporal realism).
_DAY_HOURS = (6, 7, 8, 13, 14)
_NIGHT_HOURS = (18, 19, 22, 23)

# Synthetic free-text description bank per incident type (Portuguese, BR context).
# routine has no description (no incident occurred).
_DESCRIPTIONS: dict[str, list[str]] = {
    "access_violation": [
        "Tentativa de acesso nao autorizado na {post}.",
        "Pessoa sem cracha tentou entrar pela {post}.",
        "Acesso indevido registrado proximo a {post}.",
    ],
    "equipment": [
        "Falha no equipamento de monitoramento da {post}.",
        "Camera da {post} fora de operacao.",
        "Portao automatico da {post} travado.",
    ],
    "safety": [
        "Acionamento do alarme de incendio no setor.",
        "Vazamento identificado durante a ronda.",
        "Risco de seguranca reportado na {post}.",
    ],
    "theft": [
        "Constatado furto de material no patio.",
        "Subtracao de equipamento na {post}.",
        "Suspeita de furto registrada na ronda.",
    ],
    "other": [
        "Ocorrencia diversa registrada durante a ronda.",
        "Situacao atipica observada na {post}.",
        "Registro complementar de ocorrencia.",
    ],
}


class SyntheticRecord(BaseModel):
    """One synthetic shift report (clean ground truth)."""

    record_id: str

    # Form fields (ground truth for the extraction eval).
    shift_date: date
    shift_period: str
    shift_start_hour: int
    guard_name: str
    post: str
    incident_occurred: bool
    incident_description: str | None = None

    # Classification labels (ground truth for the classification eval).
    incident_type: str
    urgency: str
    sector: str


def _sample(rng: random.Random, distribution: dict[str, float]) -> str:
    """Sample one key from a {label: probability} distribution."""
    labels = list(distribution.keys())
    weights = list(distribution.values())
    return rng.choices(labels, weights=weights, k=1)[0]


def generate_record(rng: random.Random, record_id: str) -> SyntheticRecord:
    """Generate one synthetic record using the documented joint priors."""
    # 1. Shift period (temporal anchor).
    shift_period = _sample(rng, priors.P_SHIFT_PERIOD)

    # 2. Incident occurrence conditioned on the shift period.
    p_incident = priors.P_INCIDENT_GIVEN_SHIFT[shift_period]
    incident_occurred = rng.random() < p_incident

    # 3. Type | incident (routine iff no incident).
    if incident_occurred:
        incident_type = _sample(rng, priors.P_TYPE_GIVEN_INCIDENT)
    else:
        incident_type = priors.TYPE_WHEN_NO_INCIDENT

    # 4. Urgency | type and 5. sector | type (conditional).
    urgency = _sample(rng, priors.P_URGENCY_GIVEN_TYPE[incident_type])
    sector = _sample(rng, priors.P_SECTOR_GIVEN_TYPE[incident_type])

    # 6. Staffing and post.
    guard_name = rng.choice(priors.GUARD_NAMES)
    post = rng.choice(priors.POSTS)

    # 7. Date and start hour (temporal spread).
    shift_date = _EPOCH + timedelta(days=rng.randint(0, _DATE_SPAN_DAYS - 1))
    hours = _DAY_HOURS if shift_period == "day" else _NIGHT_HOURS
    shift_start_hour = rng.choice(hours)

    # 8. Free-text description (only when an incident occurred).
    description: str | None = None
    if incident_occurred:
        template = rng.choice(_DESCRIPTIONS[incident_type])
        description = template.format(post=post)

    return SyntheticRecord(
        record_id=record_id,
        shift_date=shift_date,
        shift_period=shift_period,
        shift_start_hour=shift_start_hour,
        guard_name=guard_name,
        post=post,
        incident_occurred=incident_occurred,
        incident_description=description,
        incident_type=incident_type,
        urgency=urgency,
        sector=sector,
    )
