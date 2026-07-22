"""Pydantic models for the report-type configuration (the YAML schema).

Design rule: this is the "schema-for-the-schema" — every config/*.yaml is
validated against these models before any pipeline stage runs. Adding a new
report type means a new YAML file; no code change here.

Build order:
  FieldSchema           — one field in the report form
  ClassificationConfig  — taxonomy labels (type / urgency / sector)
  RoutingCondition      — one `when` clause in a routing rule
  RoutingRule           — condition → recipients pair
  ReportConfig          — the whole config document (top-level model)
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Field types the pipeline supports
# ---------------------------------------------------------------------------

# Scalar field/column types. "table" (repeating rows) is only valid at the field level.
ScalarFieldType = Literal["date", "string", "enum", "bool", "text"]
FieldType = Literal["date", "string", "enum", "bool", "text", "table"]


class ColumnSchema(BaseModel):
    """One column of a `table` field (e.g. Item / Hora / Descrição / Ação / Resolvido)."""

    name: str
    type: ScalarFieldType  # tables do not nest
    values: list[str] | None = None  # required when type == "enum"
    ocr_aliases: list[str] | None = None

    @model_validator(mode="after")
    def enum_requires_values(self) -> ColumnSchema:
        if self.type == "enum" and not self.values:
            raise ValueError(
                f"Column '{self.name}': type='enum' requires a non-empty 'values' list."
            )
        return self


class FieldSchema(BaseModel):
    """Schema for a single field in the handwritten report form.

    A field is scalar (date/string/enum/bool/text) or a `table` of repeating rows
    (the occurrence table). A table field declares its `columns`; a scalar field
    must not (ADR controle_ocorrencias).
    """

    name: str
    type: FieldType
    required: bool = True
    handwritten: bool = True
    # Only meaningful when type == "enum"; must be provided in that case.
    values: list[str] | None = None
    # Printed label(s) the OCR/rule extractor anchors on to find this field's value
    # (e.g. ["Data", "Dia"]). Optional; config-driven so adding a form needs no code.
    ocr_aliases: list[str] | None = None
    # Required when type == "table"; forbidden otherwise.
    columns: list[ColumnSchema] | None = None

    @model_validator(mode="after")
    def enum_requires_values(self) -> FieldSchema:
        if self.type == "enum" and not self.values:
            raise ValueError(
                f"Field '{self.name}': type='enum' requires a non-empty 'values' list."
            )
        return self

    @model_validator(mode="after")
    def table_requires_columns(self) -> FieldSchema:
        if self.type == "table" and not self.columns:
            raise ValueError(
                f"Field '{self.name}': type='table' requires a non-empty 'columns' list."
            )
        if self.type != "table" and self.columns:
            raise ValueError(f"Field '{self.name}': 'columns' is only valid for type='table'.")
        return self


# ---------------------------------------------------------------------------
# Classification taxonomy
# ---------------------------------------------------------------------------


class LabelSet(BaseModel):
    """A named set of allowed labels for one classification dimension."""

    labels: Annotated[list[str], Field(min_length=1)]


class ClassificationConfig(BaseModel):
    """Taxonomy for incident classification (type / urgency / sector)."""

    type: LabelSet
    urgency: LabelSet
    sector: LabelSet


# ---------------------------------------------------------------------------
# Routing rules (data, not code)
# ---------------------------------------------------------------------------


class RoutingCondition(BaseModel):
    """One `when` clause — a partial match on classification fields."""

    urgency: str | None = None
    type: str | None = None
    sector: str | None = None


class RoutingRule(BaseModel):
    """Maps a condition to the list of recipient groups."""

    when: RoutingCondition | None = None  # None → default / catch-all rule
    recipients: Annotated[list[str], Field(min_length=1)]


# ---------------------------------------------------------------------------
# Performance / SLO
# ---------------------------------------------------------------------------


class PerformanceConfig(BaseModel):
    """SLO and throughput knobs for the pipeline."""

    max_seconds_per_sheet: int = 300


# ---------------------------------------------------------------------------
# Top-level config document
# ---------------------------------------------------------------------------


class ReportConfig(BaseModel):
    """The complete occurrence-sheet config loaded from ``configs/*.yaml``."""

    model_config = ConfigDict(extra="forbid")

    report_type: str
    fields: Annotated[list[FieldSchema], Field(min_length=1)]
    classification: ClassificationConfig
    routing: list[RoutingRule]
    performance: PerformanceConfig | None = None

    @model_validator(mode="after")
    def routing_has_default(self) -> ReportConfig:
        """Close the executable config contract before any document is processed."""
        field_names = [field.name for field in self.fields]
        if len(field_names) != len(set(field_names)):
            raise ValueError("field names must be unique")

        table_fields = [field for field in self.fields if field.type == "table"]
        if len(table_fields) != 1:
            raise ValueError("v1 requires exactly one table field per report config")
        for table in table_fields:
            column_names = [column.name for column in table.columns or []]
            if len(column_names) != len(set(column_names)):
                raise ValueError(f"table '{table.name}' column names must be unique")

        default_indexes = [index for index, rule in enumerate(self.routing) if rule.when is None]
        if default_indexes != [len(self.routing) - 1]:
            raise ValueError("routing must contain exactly one default rule and it must be last")

        taxonomy = {
            "type": set(self.classification.type.labels),
            "urgency": set(self.classification.urgency.labels),
            "sector": set(self.classification.sector.labels),
        }
        for index, rule in enumerate(self.routing):
            if rule.when is None:
                continue
            for dimension, allowed in taxonomy.items():
                value = getattr(rule.when, dimension)
                if value is not None and value not in allowed:
                    raise ValueError(
                        f"routing[{index}].when.{dimension}={value!r} is not-in-taxonomy"
                    )
        return self
