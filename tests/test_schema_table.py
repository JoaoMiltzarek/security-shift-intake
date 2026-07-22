"""Tests for the table field type + ColumnSchema (ADR controle_ocorrencias)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.schema.config import ColumnSchema, FieldSchema
from src.schema.loader import load_config


def test_column_string_ok() -> None:
    c = ColumnSchema(name="item", type="string")
    assert c.values is None


def test_column_enum_requires_values() -> None:
    with pytest.raises(ValidationError, match="values"):
        ColumnSchema(name="resolvido", type="enum")


def test_table_field_requires_columns() -> None:
    with pytest.raises(ValidationError, match="columns"):
        FieldSchema(name="ocorrencias", type="table")


def test_table_field_with_columns_ok() -> None:
    f = FieldSchema(
        name="ocorrencias",
        type="table",
        required=False,
        columns=[ColumnSchema(name="item", type="string")],
    )
    assert f.columns is not None
    assert f.columns[0].name == "item"


def test_scalar_field_with_columns_raises() -> None:
    with pytest.raises(ValidationError, match="columns"):
        FieldSchema(name="x", type="string", columns=[ColumnSchema(name="c", type="string")])


def test_load_controle_ocorrencias_config() -> None:
    cfg = load_config(Path("configs/controle_ocorrencias.yaml"))
    assert cfg.report_type == "controle_ocorrencias"
    table = next(f for f in cfg.fields if f.type == "table")
    assert table.name == "ocorrencias"
    assert table.columns is not None
    assert [c.name for c in table.columns] == ["item", "hora", "descricao", "acao", "resolvido"]
    resolvido = next(c for c in table.columns if c.name == "resolvido")
    assert resolvido.values == ["sim", "nao"]
