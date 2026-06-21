"""M1.a: unit tests for FieldSchema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.schema.config import FieldSchema


def test_valid_string_field() -> None:
    f = FieldSchema(name="guard_name", type="string", required=True)
    assert f.name == "guard_name"
    assert f.values is None


def test_valid_enum_field_with_values() -> None:
    f = FieldSchema(name="shift_period", type="enum", values=["day", "night"])
    assert f.values == ["day", "night"]


def test_valid_bool_field() -> None:
    f = FieldSchema(name="incident_occurred", type="bool", required=True)
    assert f.type == "bool"


def test_valid_date_field() -> None:
    f = FieldSchema(name="shift_date", type="date")
    assert f.required is True
    assert f.handwritten is True


def test_valid_text_field_optional() -> None:
    f = FieldSchema(name="incident_description", type="text", required=False)
    assert f.required is False


def test_enum_without_values_raises() -> None:
    with pytest.raises(ValidationError, match="values"):
        FieldSchema(name="shift_period", type="enum")


def test_enum_with_empty_values_raises() -> None:
    with pytest.raises(ValidationError, match="values"):
        FieldSchema(name="shift_period", type="enum", values=[])


def test_invalid_type_raises() -> None:
    with pytest.raises(ValidationError):
        FieldSchema(name="x", type="integer")  # type: ignore[arg-type]
