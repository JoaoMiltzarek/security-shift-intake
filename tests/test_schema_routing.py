"""M1.b: unit tests for ClassificationConfig and RoutingRule."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.schema.config import ClassificationConfig, LabelSet, RoutingCondition, RoutingRule

# ---------------------------------------------------------------------------
# ClassificationConfig
# ---------------------------------------------------------------------------


def test_valid_classification_config() -> None:
    cfg = ClassificationConfig(
        type=LabelSet(labels=["routine", "theft", "safety"]),
        urgency=LabelSet(labels=["low", "medium", "high", "critical"]),
        sector=LabelSet(labels=["tech_security", "general_support", "facilities"]),
    )
    assert "routine" in cfg.type.labels
    assert "critical" in cfg.urgency.labels


def test_label_set_empty_raises() -> None:
    with pytest.raises(ValidationError):
        LabelSet(labels=[])


# ---------------------------------------------------------------------------
# RoutingCondition
# ---------------------------------------------------------------------------


def test_routing_condition_all_none_is_default() -> None:
    cond = RoutingCondition()
    assert cond.urgency is None
    assert cond.type is None
    assert cond.sector is None


def test_routing_condition_partial() -> None:
    cond = RoutingCondition(urgency="critical")
    assert cond.urgency == "critical"
    assert cond.type is None


# ---------------------------------------------------------------------------
# RoutingRule
# ---------------------------------------------------------------------------


def test_routing_rule_with_condition() -> None:
    rule = RoutingRule(
        when=RoutingCondition(urgency="critical"),
        recipients=["tech_security_oncall", "general_support"],
    )
    assert rule.when is not None
    assert "tech_security_oncall" in rule.recipients


def test_routing_rule_default_catch_all() -> None:
    rule = RoutingRule(when=None, recipients=["general_support"])
    assert rule.when is None


def test_routing_rule_empty_recipients_raises() -> None:
    with pytest.raises(ValidationError):
        RoutingRule(when=None, recipients=[])
