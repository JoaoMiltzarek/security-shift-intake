"""Documented generative priors for the HT Micron security shift report (Tier A).

> **Source of all priors below:** elicited from operator domain knowledge of the
> real job (the human who performs this transcription daily). They are deliberately
> NOT uniform-random. Each distribution is documented inline with its rationale.
> These are synthetic priors for a synthetic dataset — no real data is encoded.

Design rules (see skills/synthetic-data-generation/SKILL.md):
  - Preserve JOINT distributions, not just marginals.
  - `urgency | type` and `sector | type` are conditional, not independent.
  - `incident | shift_period` captures the temporal (day/night) effect.

The label vocabularies here MUST stay consistent with
configs/htmicron_security.yaml (enforced by a test in M2.a).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Label vocabularies (must match configs/htmicron_security.yaml)
# ---------------------------------------------------------------------------

TYPE_LABELS = ["routine", "access_violation", "equipment", "safety", "theft", "other"]
URGENCY_LABELS = ["low", "medium", "high", "critical"]
SECTOR_LABELS = ["tech_security", "general_support", "facilities"]

SHIFT_PERIODS = ["day", "night"]

# A distribution is a mapping label -> probability. Helpers validate they sum to 1.
Distribution = dict[str, float]


# ---------------------------------------------------------------------------
# Temporal effect: P(incident occurred | shift_period)
# Rationale: night shifts see more notable events (access attempts, equipment
# faults discovered, fewer staff around). Overall incident rate ~0.30, i.e. ~70%
# of shifts are routine/no-incident — matches the "~70% no notable incident" prior.
# ---------------------------------------------------------------------------

P_INCIDENT_GIVEN_SHIFT: dict[str, float] = {
    "day": 0.22,
    "night": 0.38,
}

# Marginal over shift periods (roughly balanced, slight day skew for scheduling).
P_SHIFT_PERIOD: Distribution = {
    "day": 0.52,
    "night": 0.48,
}


# ---------------------------------------------------------------------------
# Type distribution GIVEN an incident occurred (excludes "routine").
# Rationale: skewed — access violations and equipment faults are the everyday
# incidents; theft and safety events are rarer; "other" is the long tail.
# ---------------------------------------------------------------------------

P_TYPE_GIVEN_INCIDENT: Distribution = {
    "access_violation": 0.34,
    "equipment": 0.30,
    "safety": 0.16,
    "theft": 0.12,
    "other": 0.08,
}

# When no incident occurred, the type is deterministically "routine".
TYPE_WHEN_NO_INCIDENT = "routine"


# ---------------------------------------------------------------------------
# P(urgency | type) — conditional, NOT independent.
# Rationale: a safety event (e.g. fire alarm) is never "low"; equipment issues
# skew low/medium; theft and safety carry real high/critical mass.
# ---------------------------------------------------------------------------

P_URGENCY_GIVEN_TYPE: dict[str, Distribution] = {
    "routine": {"low": 1.0, "medium": 0.0, "high": 0.0, "critical": 0.0},
    "equipment": {"low": 0.45, "medium": 0.40, "high": 0.13, "critical": 0.02},
    "access_violation": {"low": 0.25, "medium": 0.45, "high": 0.25, "critical": 0.05},
    "safety": {"low": 0.05, "medium": 0.30, "high": 0.45, "critical": 0.20},
    "theft": {"low": 0.05, "medium": 0.35, "high": 0.45, "critical": 0.15},
    "other": {"low": 0.30, "medium": 0.40, "high": 0.25, "critical": 0.05},
}


# ---------------------------------------------------------------------------
# P(sector | type) — mostly deterministic mapping, with occasional ambiguity.
# Rationale: equipment -> facilities; access/theft -> tech_security; safety is
# split (facilities for hazards, general support for coordination). The small
# off-diagonal mass is the "occasional ambiguity" the critic must surface.
# ---------------------------------------------------------------------------

P_SECTOR_GIVEN_TYPE: dict[str, Distribution] = {
    "routine": {"tech_security": 0.0, "general_support": 1.0, "facilities": 0.0},
    "equipment": {"tech_security": 0.0, "general_support": 0.10, "facilities": 0.90},
    "access_violation": {"tech_security": 0.92, "general_support": 0.08, "facilities": 0.0},
    "safety": {"tech_security": 0.15, "general_support": 0.30, "facilities": 0.55},
    "theft": {"tech_security": 0.88, "general_support": 0.12, "facilities": 0.0},
    "other": {"tech_security": 0.20, "general_support": 0.70, "facilities": 0.10},
}


# ---------------------------------------------------------------------------
# Staffing: synthetic guard names and posts (clearly synthetic, no real people).
# ---------------------------------------------------------------------------

GUARD_NAMES = [
    "A. Souza", "B. Lima", "C. Pereira", "D. Oliveira", "E. Costa",
    "F. Almeida", "G. Rocha", "H. Martins", "I. Barbosa", "J. Ferreira",
    "K. Gomes", "L. Ribeiro", "M. Carvalho", "N. Teixeira", "O. Dias",
]

POSTS = [
    "Portaria 1", "Portaria 2", "Guarita Norte", "Guarita Sul",
    "Ronda Interna", "Doca de Carga", "Recepcao",
]


# ---------------------------------------------------------------------------
# Tier C priors — occurrence-table sheet "Controle de ocorrências"
# (docs/DATASET_CONTRACT.md §6; same elicitation source as the priors above).
# ---------------------------------------------------------------------------

# P(sheet is S/A | profile): "balanced" oversamples occurrences on purpose (more
# measurable signal per sheet); "operational" matches the real-world ~70% no-incident
# prior. The two profiles are NEVER mixed in one dataset (contract §6).
P_SA_GIVEN_PROFILE: dict[str, float] = {
    "balanced": 0.50,
    "operational": 0.70,
}

# When a sheet has no occurrence, the guard either writes "S/A" or strikes the cells
# through. Striking is the rarer habit.
P_RISCADO_GIVEN_NO_OCCURRENCE = 0.25

# P(number of table rows | sheet has occurrences): most sheets log one incident.
P_N_OCORRENCIAS_GIVEN_OCCURRENCE: dict[int, float] = {1: 0.55, 2: 0.30, 3: 0.15}

# P(number of guards on the header): the real sheet lists several names.
P_N_VIGILANTES: dict[int, float] = {1: 0.35, 2: 0.45, 3: 0.20}

# P(an occurrence with a time records BOTH entry and exit times) — contract §6.
P_HORA_DUPLA = 0.30

# P(resolvido column value): "em_branco" = guard left it blank (maps to None).
P_RESOLVIDO: Distribution = {"sim": 0.60, "nao": 0.25, "em_branco": 0.15}

# Fictional units (mix of generic numbering and invented post names — contract §7).
UNIDADES = [
    "Unidade 01", "Unidade 02", "Unidade 03", "Unidade 05", "Unidade 07",
    "Unidade 09", "Unidade 12", "Posto Delta", "Posto Horizonte", "Posto Mirante",
]


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_TOLERANCE = 1e-9


def is_valid_distribution(dist: Distribution, tolerance: float = 1e-6) -> bool:
    """True if probabilities are non-negative and sum to 1 (within tolerance)."""
    if not dist:
        return False
    if any(p < 0 for p in dist.values()):
        return False
    return abs(sum(dist.values()) - 1.0) <= tolerance


def validate_all_priors() -> None:
    """Raise ValueError if any documented prior is malformed. Called by tests."""
    if not is_valid_distribution(P_SHIFT_PERIOD):
        raise ValueError("P_SHIFT_PERIOD does not sum to 1.")
    if not is_valid_distribution(P_TYPE_GIVEN_INCIDENT):
        raise ValueError("P_TYPE_GIVEN_INCIDENT does not sum to 1.")
    for t, dist in P_URGENCY_GIVEN_TYPE.items():
        if not is_valid_distribution(dist):
            raise ValueError(f"P_URGENCY_GIVEN_TYPE[{t!r}] does not sum to 1.")
    for t, dist in P_SECTOR_GIVEN_TYPE.items():
        if not is_valid_distribution(dist):
            raise ValueError(f"P_SECTOR_GIVEN_TYPE[{t!r}] does not sum to 1.")
    for period, p in P_INCIDENT_GIVEN_SHIFT.items():
        if not 0.0 <= p <= 1.0:
            raise ValueError(f"P_INCIDENT_GIVEN_SHIFT[{period!r}] out of [0,1].")
    # --- Tier C priors (contract §6) ---
    if not is_valid_distribution(P_RESOLVIDO):
        raise ValueError("P_RESOLVIDO does not sum to 1.")
    for name, int_dist in {
        "P_N_OCORRENCIAS_GIVEN_OCCURRENCE": P_N_OCORRENCIAS_GIVEN_OCCURRENCE,
        "P_N_VIGILANTES": P_N_VIGILANTES,
    }.items():
        if abs(sum(int_dist.values()) - 1.0) > 1e-6 or any(p < 0 for p in int_dist.values()):
            raise ValueError(f"{name} is not a valid distribution.")
    for name, prob in {
        **{f"P_SA_GIVEN_PROFILE[{k!r}]": v for k, v in P_SA_GIVEN_PROFILE.items()},
        "P_RISCADO_GIVEN_NO_OCCURRENCE": P_RISCADO_GIVEN_NO_OCCURRENCE,
        "P_HORA_DUPLA": P_HORA_DUPLA,
    }.items():
        if not 0.0 <= prob <= 1.0:
            raise ValueError(f"{name} out of [0,1].")
