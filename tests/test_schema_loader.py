"""M1.d: unit tests for load_config — valid YAML succeeds, invalid YAML fails clearly.

These tests use tmp_path fixtures (no disk state) so they are fully isolated.
The committed occurrence-sheet integration is exercised in test_schema_table.py
(M1.e), which requires the real config file to exist.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from src.schema.loader import config_fingerprint, load_config


def _write_yaml(tmp_path: Path, name: str, data: object) -> Path:
    p = tmp_path / name
    p.write_text(yaml.dump(data), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Minimal valid config structure (enough to pass ReportConfig validation)
# ---------------------------------------------------------------------------

VALID_CONFIG: dict[str, Any] = {
    "report_type": "test_report",
    "fields": [
        {"name": "guard_name", "type": "string", "required": True},
        {"name": "shift_period", "type": "enum", "values": ["day", "night"]},
        {
            "name": "occurrences",
            "type": "table",
            "required": False,
            "columns": [{"name": "description", "type": "text"}],
        },
    ],
    "classification": {
        "type": {"labels": ["routine", "safety"]},
        "urgency": {"labels": ["low", "high"]},
        "sector": {"labels": ["general_support"]},
        "rules": [
            {
                "id": "classification.default",
                "keywords": [],
                "type": "routine",
                "urgency": "low",
                "sector": "general_support",
            }
        ],
    },
    "routing": [
        {
            "id": "routing.high",
            "when": {"urgency": "high"},
            "recipients": ["tech_security"],
        },
        {"id": "routing.default", "recipients": ["general_support"]},
    ],
    "performance": {"max_seconds_per_sheet": 300},
}


def test_valid_config_loads_successfully(tmp_path: Path) -> None:
    path = _write_yaml(tmp_path, "valid.yaml", VALID_CONFIG)
    cfg = load_config(path)
    assert cfg.report_type == "test_report"
    assert len(cfg.fields) == 3
    assert cfg.classification.urgency.labels == ["low", "high"]
    assert cfg.performance.max_seconds_per_sheet == 300


def test_config_fingerprint_is_stable_and_content_addressed(tmp_path: Path) -> None:
    config = load_config(_write_yaml(tmp_path, "valid.yaml", VALID_CONFIG))
    same = load_config(_write_yaml(tmp_path, "same.yaml", copy.deepcopy(VALID_CONFIG)))
    changed_payload = copy.deepcopy(VALID_CONFIG)
    changed_payload["report_type"] = "other_report"
    changed = load_config(_write_yaml(tmp_path, "changed.yaml", changed_payload))

    assert config_fingerprint(config) == config_fingerprint(same)
    assert config_fingerprint(config) != config_fingerprint(changed)
    assert len(config_fingerprint(config)) == 64


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
    bad["routing"] = [
        {
            "id": "routing.high",
            "when": {"urgency": "high"},
            "recipients": ["tech_security"],
        }
    ]
    path = _write_yaml(tmp_path, "bad.yaml", bad)
    with pytest.raises(ValidationError, match="default"):
        load_config(path)


def test_routing_default_must_be_unique_and_last(tmp_path: Path) -> None:
    bad = copy.deepcopy(VALID_CONFIG)
    bad["routing"] = [
        {"id": "routing.first", "recipients": ["general_support"]},
        {
            "id": "routing.high",
            "when": {"urgency": "high"},
            "recipients": ["tech_security"],
        },
        {"id": "routing.last", "recipients": ["other"]},
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


def test_empty_routing_condition_is_rejected(tmp_path: Path) -> None:
    bad = copy.deepcopy(VALID_CONFIG)
    bad["routing"][0]["when"] = {}

    with pytest.raises(ValidationError, match="cannot be empty"):
        load_config(_write_yaml(tmp_path, "bad.yaml", bad))


def test_shadowed_routing_condition_is_rejected(tmp_path: Path) -> None:
    bad = copy.deepcopy(VALID_CONFIG)
    bad["routing"] = [
        {
            "id": "routing.high",
            "when": {"urgency": "high"},
            "recipients": ["tech_security"],
        },
        {
            "id": "routing.high_safety",
            "when": {"urgency": "high", "type": "safety"},
            "recipients": ["general_support"],
        },
        {"id": "routing.default", "recipients": ["general_support"]},
    ]

    with pytest.raises(ValidationError, match=r"routing\[1\].*shadowed.*routing\[0\]"):
        load_config(_write_yaml(tmp_path, "bad.yaml", bad))


def test_classification_rule_ids_must_be_unique(tmp_path: Path) -> None:
    bad = copy.deepcopy(VALID_CONFIG)
    fallback = copy.deepcopy(bad["classification"]["rules"][0])
    fallback["keywords"] = ["alarme"]
    bad["classification"]["rules"].insert(0, fallback)

    with pytest.raises(ValidationError, match="rule ids must be unique"):
        load_config(_write_yaml(tmp_path, "bad.yaml", bad))


def test_classification_requires_one_final_fallback(tmp_path: Path) -> None:
    bad = copy.deepcopy(VALID_CONFIG)
    bad["classification"]["rules"][0]["keywords"] = ["alarme"]

    with pytest.raises(ValidationError, match="fallback"):
        load_config(_write_yaml(tmp_path, "bad.yaml", bad))


def test_classification_rules_must_reference_taxonomy(tmp_path: Path) -> None:
    bad = copy.deepcopy(VALID_CONFIG)
    bad["classification"]["rules"][0]["type"] = "invented"

    with pytest.raises(ValidationError, match="not-in-taxonomy"):
        load_config(_write_yaml(tmp_path, "bad.yaml", bad))


def test_routing_rule_ids_must_be_unique(tmp_path: Path) -> None:
    bad = copy.deepcopy(VALID_CONFIG)
    bad["routing"][1]["id"] = bad["routing"][0]["id"]

    with pytest.raises(ValidationError, match="routing rule ids must be unique"):
        load_config(_write_yaml(tmp_path, "bad.yaml", bad))


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
    with pytest.raises(ValidationError, match="exactly one table"):
        load_config(path)


def test_config_without_occurrence_table_is_rejected(tmp_path: Path) -> None:
    bad = copy.deepcopy(VALID_CONFIG)
    bad["fields"] = [field for field in bad["fields"] if field["type"] != "table"]

    with pytest.raises(ValidationError, match="exactly one table"):
        load_config(_write_yaml(tmp_path, "bad.yaml", bad))


def test_scalar_email_template_is_rejected(tmp_path: Path) -> None:
    bad = copy.deepcopy(VALID_CONFIG)
    bad["email_template"] = "templates/legacy.j2"

    with pytest.raises(ValidationError, match="extra_forbidden"):
        load_config(_write_yaml(tmp_path, "bad.yaml", bad))


@pytest.mark.parametrize(
    ("path", "unknown_key"),
    [
        (("fields", 0), "requiredd"),
        (("fields", 2, "columns", 0), "ocr_aliasses"),
        (("classification",), "urgenc"),
        (("classification", "type"), "label"),
        (("classification", "rules", 0), "keyword"),
        (("routing", 0), "recipient"),
        (("routing", 0, "when"), "urgenc"),
        (("performance",), "max_second_per_sheet"),
    ],
)
def test_unknown_nested_keys_are_rejected(
    tmp_path: Path, path: tuple[str | int, ...], unknown_key: str
) -> None:
    bad = copy.deepcopy(VALID_CONFIG)
    bad["performance"] = {"max_seconds_per_sheet": 300}
    target: object = bad
    for member in path:
        target = target[member]  # type: ignore[index]
    assert isinstance(target, dict)
    target[unknown_key] = "typo"

    with pytest.raises(ValidationError, match="extra_forbidden"):
        load_config(_write_yaml(tmp_path, "bad.yaml", bad))


@pytest.mark.parametrize(
    "duplicate",
    [
        "report_type: test_report\nreport_type: shadowed\n",
        "- name: guard_name\n  name: shadowed\n",
        "    urgency: high\n    urgency: low\n",
    ],
    ids=["top-level", "sequence-member", "nested-condition"],
)
def test_duplicate_yaml_keys_are_rejected(tmp_path: Path, duplicate: str) -> None:
    rendered = yaml.safe_dump(VALID_CONFIG, sort_keys=False)
    if duplicate.startswith("report_type"):
        rendered = rendered.replace("report_type: test_report\n", duplicate, 1)
    elif duplicate.startswith("- name"):
        rendered = rendered.replace("- name: guard_name\n", duplicate, 1)
    else:
        rendered = rendered.replace("    urgency: high\n", duplicate, 1)
    path = tmp_path / "duplicate.yaml"
    path.write_text(rendered, encoding="utf-8")

    with pytest.raises(yaml.YAMLError, match="duplicate key"):
        load_config(path)


def test_processing_budget_is_required(tmp_path: Path) -> None:
    bad = copy.deepcopy(VALID_CONFIG)
    del bad["performance"]

    with pytest.raises(ValidationError, match="performance"):
        load_config(_write_yaml(tmp_path, "bad.yaml", bad))


@pytest.mark.parametrize("value", [0, -1, 901, float("inf"), float("nan"), True])
def test_processing_budget_must_be_finite_integer_within_bounds(
    tmp_path: Path, value: object
) -> None:
    bad = copy.deepcopy(VALID_CONFIG)
    bad["performance"]["max_seconds_per_sheet"] = value

    with pytest.raises(ValidationError, match="max_seconds_per_sheet"):
        load_config(_write_yaml(tmp_path, "bad.yaml", bad))


def test_empty_label_set_raises(tmp_path: Path) -> None:
    bad = dict(VALID_CONFIG)
    bad["classification"] = {
        "type": {"labels": []},  # empty → should fail
        "urgency": {"labels": ["low"]},
        "sector": {"labels": ["support"]},
        "rules": [],
    }
    path = _write_yaml(tmp_path, "bad.yaml", bad)
    with pytest.raises(ValidationError):
        load_config(path)


def test_file_not_found_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nonexistent.yaml")
