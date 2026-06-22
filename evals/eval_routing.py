"""Routing eval: recipient-selection accuracy vs the documented YAML rules.

Routing is deterministic, so this is a regression guard (near-100% expected,
spec §6). Accuracy is measured against a hand-specified expectation table — not
re-derived from the config — so a rule change that breaks intent is caught.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.pipeline.route import select_recipients
from src.schema.loader import load_config
from src.schema.state import Classification

CONFIG_PATH = Path("configs/htmicron_security.yaml")

# (incident_type, urgency, sector) -> expected recipients (the documented intent).
_EXPECTATIONS: list[tuple[tuple[str, str, str], list[str]]] = [
    (("safety", "critical", "facilities"), ["tech_security_oncall", "general_support"]),
    (("theft", "critical", "tech_security"), ["tech_security_oncall", "general_support"]),
    (("theft", "high", "tech_security"), ["tech_security", "general_support"]),
    (("equipment", "medium", "facilities"), ["facilities"]),
    (("access_violation", "medium", "tech_security"), ["tech_security"]),
    (("routine", "low", "general_support"), ["general_support"]),
    (("other", "low", "general_support"), ["general_support"]),
]


def run() -> dict[str, Any]:
    """Compare select_recipients against the expectation table."""
    config = load_config(CONFIG_PATH)
    matches = 0
    mismatches: list[dict[str, Any]] = []

    for (itype, urgency, sector), expected in _EXPECTATIONS:
        cls = Classification(
            incident_type=itype, urgency=urgency, sector=sector, confidence=1.0
        )
        actual = select_recipients(cls, config)
        if actual == expected:
            matches += 1
        else:
            mismatches.append(
                {"input": [itype, urgency, sector], "expected": expected, "actual": actual}
            )

    n = len(_EXPECTATIONS)
    return {
        "component": "routing",
        "n_cases": n,
        "accuracy": matches / n,
        "mismatches": mismatches,
    }
