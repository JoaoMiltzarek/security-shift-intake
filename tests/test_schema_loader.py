"""M1.d: unit tests for load_config — valid YAML succeeds, invalid YAML fails clearly.

These tests use tmp_path fixtures (no disk state) so they are fully isolated.
The htmicron_security.yaml integration is exercised in test_schema_config_integration.py
(M1.e), which requires the real config file to exist.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from src.schema.loader import load_config


def _write_yaml(tmp_path: Path, name: str, data: object) -> Path:
    p = tmp_path / name
    p.write_text(yaml.dump(data), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Minimal valid config structure (enough to pass ReportConfig validation)
# ---------------------------------------------------------------------------

VALID_CONFIG: dict = {
    "report_type": "test_report",
    "fields": [
        {"name": "guard_name", "type": "string", "required": True},
        {"name": "shift_period", "type": "enum", "values": ["day", "night"]},
    ],
    "classification": {
        "type": {"labels": ["routine", "safety"]},
        "urgency": {"labels": ["low", "high"]},
        "sector": {"labels": ["general_support"]},
    },
    "routing": [
        {"when": {"urgency": "high"}, "recipients": ["tech_security"]},
        {"recipients": ["general_support"]},  # default (when omitted)
    ],
    "email_template": "templates/test.j2",
}


def test_valid_config_loads_successfully(tmp_path: Path) -> None:
    path = _write_yaml(tmp_path, "valid.yaml", VALID_CONFIG)
    cfg = load_config(path)
    assert cfg.report_type == "test_report"
    assert len(cfg.fields) == 2
    assert cfg.classification.urgency.labels == ["low", "high"]


def test_valid_config_routing_default_present(tmp_path: Path) -> None:
    path = _write_yaml(tmp_path, "valid.yaml", VALID_CONFIG)
    cfg = load_config(path)
    defaults = [r for r in cfg.routing if r.when is None]
    assert len(defaults) == 1


def test_missing_required_field_raises(tmp_path: Path) -> None:
    bad = {**VALID_CONFIG}
    del bad["report_type"]
    path = _write_yaml(tmp_path, "bad.yaml", bad)
    with pytest.raises(ValidationError, match="report_type"):
        load_config(path)


def test_enum_field_missing_values_raises(tmp_path: Path) -> None:
    bad = dict(VALID_CONFIG)
    bad["fields"] = [{"name": "shift_period", "type": "enum"}]  # no values
    path = _write_yaml(tmp_path, "bad.yaml", bad)
    with pytest.raises(ValidationError, match="values"):
        load_config(path)


def test_routing_without_default_raises(tmp_path: Path) -> None:
    bad = dict(VALID_CONFIG)
    bad["routing"] = [{"when": {"urgency": "high"}, "recipients": ["tech_security"]}]
    path = _write_yaml(tmp_path, "bad.yaml", bad)
    with pytest.raises(ValidationError, match="default"):
        load_config(path)


def test_routing_default_must_be_unique_and_last(tmp_path: Path) -> None:
    bad = copy.deepcopy(VALID_CONFIG)
    bad["routing"] = [
        {"recipients": ["general_support"]},
        {"when": {"urgency": "high"}, "recipients": ["tech_security"]},
        {"recipients": ["other"]},
    ]
    path = _write_yaml(tmp_path, "bad.yaml", bad)
    with pytest.raises(ValidationError, match="exactly one default.*last"):
        load_config(path)


def test_routing_conditions_must_reference_taxonomy(tmp_path: Path) -> None:
    bad = copy.deepcopy(VALID_CONFIG)
    bad["routing"][0]["when"] = {"urgency": "not-in-taxonomy"}
    path = _write_yaml(tmp_path, "bad.yaml", bad)
    with pytest.raises(ValidationError, match="not-in-taxonomy"):
        load_config(path)


def test_field_names_must_be_unique(tmp_path: Path) -> None:
    bad = copy.deepcopy(VALID_CONFIG)
    bad["fields"].append({"name": "guard_name", "type": "string"})
    path = _write_yaml(tmp_path, "bad.yaml", bad)
    with pytest.raises(ValidationError, match="field names must be unique"):
        load_config(path)


def test_only_one_repeating_table_is_supported(tmp_path: Path) -> None:
    bad = copy.deepcopy(VALID_CONFIG)
    table = {
        "name": "rows_a",
        "type": "table",
        "columns": [{"name": "description", "type": "text"}],
    }
    bad["fields"] = [table, {**table, "name": "rows_b"}]
    path = _write_yaml(tmp_path, "bad.yaml", bad)
    with pytest.raises(ValidationError, match="at most one table"):
        load_config(path)


def test_empty_label_set_raises(tmp_path: Path) -> None:
    bad = dict(VALID_CONFIG)
    bad["classification"] = {
        "type": {"labels": []},  # empty → should fail
        "urgency": {"labels": ["low"]},
        "sector": {"labels": ["support"]},
    }
    path = _write_yaml(tmp_path, "bad.yaml", bad)
    with pytest.raises(ValidationError):
        load_config(path)


def test_file_not_found_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nonexistent.yaml")
