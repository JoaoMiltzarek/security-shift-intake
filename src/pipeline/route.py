"""Stage 5a — Route: deterministic recipient selection from the YAML rules.

Routing is a business rule, not an ML problem (spec §2): keep it auditable and
config-driven. Rules are evaluated in order; the first whose `when` matches the
classification wins, and the catch-all (`when: null`) — required to be present and
last by the config validator — is the fallback.
"""

from __future__ import annotations

from src.schema.config import ReportConfig, RoutingCondition
from src.schema.state import Classification, PipelineState, RoutingDecision


def _matches(condition: RoutingCondition, classification: Classification) -> bool:
    """True if every field set on the condition equals the classification's value."""
    checks = (
        (condition.type, classification.incident_type),
        (condition.urgency, classification.urgency),
        (condition.sector, classification.sector),
    )
    return all(expected is None or expected == actual for expected, actual in checks)


def select_route(classification: Classification, config: ReportConfig) -> RoutingDecision:
    """Return the first matching server-side routing decision."""
    for rule in config.routing:
        # A None `when` is the catch-all; reaching it means nothing earlier matched.
        if rule.when is None or _matches(rule.when, classification):
            return RoutingDecision(rule_id=rule.id, recipients=list(rule.recipients))
    raise ValueError("validated routing config did not contain a fallback")


def select_recipients(classification: Classification, config: ReportConfig) -> list[str]:
    """Compatibility projection for callers that only need recipient groups."""
    return select_route(classification, config).recipients


def route(state: PipelineState, config: ReportConfig) -> RoutingDecision:
    """Derive a route without persisting client-forgeable recipients."""
    if state.classification is None:
        raise ValueError("route() requires a classification; run classify first.")
    return select_route(state.classification, config)
