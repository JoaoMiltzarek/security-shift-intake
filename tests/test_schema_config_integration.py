"""M1.e integration test: load the real htmicron_security.yaml and assert its structure.

This is the only test that reads a file from configs/ — it verifies that the
committed config passes validation and has the expected shape.
"""

from __future__ import annotations

from pathlib import Path

from src.schema.loader import load_config

CONFIG_PATH = Path("configs/htmicron_security.yaml")


def test_htmicron_config_loads() -> None:
    cfg = load_config(CONFIG_PATH)
    assert cfg.report_type == "htmicron_security_shift"


def test_htmicron_config_has_required_fields() -> None:
    cfg = load_config(CONFIG_PATH)
    names = {f.name for f in cfg.fields}
    assert {"shift_date", "guard_name", "post", "shift_period", "incident_occurred"} <= names


def test_htmicron_config_incident_description_is_optional() -> None:
    cfg = load_config(CONFIG_PATH)
    desc = next(f for f in cfg.fields if f.name == "incident_description")
    assert desc.required is False


def test_htmicron_config_shift_period_enum() -> None:
    cfg = load_config(CONFIG_PATH)
    sp = next(f for f in cfg.fields if f.name == "shift_period")
    assert sp.type == "enum"
    assert set(sp.values or []) == {"day", "night"}


def test_htmicron_config_urgency_labels() -> None:
    cfg = load_config(CONFIG_PATH)
    assert "critical" in cfg.classification.urgency.labels


def test_htmicron_config_routing_has_default() -> None:
    cfg = load_config(CONFIG_PATH)
    defaults = [r for r in cfg.routing if r.when is None]
    assert len(defaults) == 1, "exactly one catch-all routing rule expected"


def test_htmicron_config_critical_urgency_routes_to_oncall() -> None:
    cfg = load_config(CONFIG_PATH)
    critical_rule = next(
        (r for r in cfg.routing if r.when and r.when.urgency == "critical"), None
    )
    assert critical_rule is not None
    assert "tech_security_oncall" in critical_rule.recipients
