"""Stage 5a — Route: deterministic recipient selection from the YAML rules.

Routing is a business rule, not an ML problem (spec §2): keep it auditable and
config-driven. Rules are evaluated in order; the first whose `when` matches the
classification wins, and the catch-all (`when: null`) — required to be present and
last by the config validator — is the fallback.
"""

from __future__ import annotations

from src.schema.config import ReportConfig, RoutingCondition
from src.schema.state import Classification, PipelineState


def _matches(condition: RoutingCondition, classification: Classification) -> bool:
    """True if every field set on the condition equals the classification's value."""
    checks = (
        (condition.type, classification.incident_type),
        (condition.urgency, classification.urgency),
        (condition.sector, classification.sector),
    )
    return all(expected is None or expected == actual for expected, actual in checks)


def select_recipients(classification: Classification, config: ReportConfig) -> list[str]:
    """Return the recipients for *classification* per the config routing rules."""
    for rule in config.routing:
        # A None `when` is the catch-all; reaching it means nothing earlier matched.
        if rule.when is None or _matches(rule.when, classification):
            return list(rule.recipients)
    return []  # unreachable: config requires a default rule


def route(state: PipelineState, config: ReportConfig) -> PipelineState:
    """Set recipients on the state from the classification. Requires classification."""
    if state.classification is None:
        raise ValueError("route() requires a classification; run classify first.")
    recipients = select_recipients(state.classification, config)
    return state.model_copy(update={"recipients": recipients})
