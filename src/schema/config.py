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


class StrictConfigModel(BaseModel):
    """Reject configuration keys that are not part of the executable contract."""

    model_config = ConfigDict(extra="forbid")


class ColumnSchema(StrictConfigModel):
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


class FieldSchema(StrictConfigModel):
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


class LabelSet(StrictConfigModel):
    """A named set of allowed labels for one classification dimension."""

    labels: Annotated[list[str], Field(min_length=1)]


class ClassificationRule(StrictConfigModel):
    """Ordered keyword rule; an empty keyword list is the final fallback."""

    id: str
    keywords: list[str] = Field(default_factory=list)
    type: str
    urgency: str
    sector: str


class ClassificationConfig(StrictConfigModel):
    """Taxonomy for incident classification (type / urgency / sector)."""

    type: LabelSet
    urgency: LabelSet
    sector: LabelSet
    rules: Annotated[list[ClassificationRule], Field(min_length=1)]


# ---------------------------------------------------------------------------
# Routing rules (data, not code)
# ---------------------------------------------------------------------------


class RoutingCondition(StrictConfigModel):
    """One `when` clause — a partial match on classification fields."""

    urgency: str | None = None
    type: str | None = None
    sector: str | None = None


class RoutingRule(StrictConfigModel):
    """Maps a condition to the list of recipient groups."""

    id: str
    when: RoutingCondition | None = None  # None → default / catch-all rule
    recipients: Annotated[list[str], Field(min_length=1)]


# ---------------------------------------------------------------------------
# Performance / SLO
# ---------------------------------------------------------------------------


class PerformanceConfig(StrictConfigModel):
    """SLO and throughput knobs for the pipeline."""

    max_seconds_per_sheet: Annotated[int, Field(strict=True, ge=1, le=900)]


# ---------------------------------------------------------------------------
# Top-level config document
# ---------------------------------------------------------------------------


class ReportConfig(StrictConfigModel):
    """The complete occurrence-sheet config loaded from ``configs/*.yaml``."""

    report_type: str
    fields: Annotated[list[FieldSchema], Field(min_length=1)]
    classification: ClassificationConfig
    routing: list[RoutingRule]
    performance: PerformanceConfig

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
        for dimension, labels in taxonomy.items():
            configured = getattr(self.classification, dimension).labels
            if len(labels) != len(configured):
                raise ValueError(f"classification.{dimension}.labels must be unique")
            if any(not label.strip() for label in configured):
                raise ValueError(f"classification.{dimension}.labels cannot contain blanks")

        classification_ids = [
            classification_rule.id for classification_rule in self.classification.rules
        ]
        if any(not rule_id.strip() for rule_id in classification_ids):
            raise ValueError("classification rule ids cannot be blank")
        if len(classification_ids) != len(set(classification_ids)):
            raise ValueError("classification rule ids must be unique")
        fallback_indexes = [
            index
            for index, classification_rule in enumerate(self.classification.rules)
            if not classification_rule.keywords
        ]
        if fallback_indexes != [len(self.classification.rules) - 1]:
            raise ValueError(
                "classification rules require exactly one empty-keyword fallback, last"
            )
        seen_keywords: set[str] = set()
        for index, classification_rule in enumerate(self.classification.rules):
            for dimension, allowed in taxonomy.items():
                value = getattr(classification_rule, dimension)
                if value not in allowed:
                    raise ValueError(
                        f"classification.rules[{index}].{dimension}={value!r} is not-in-taxonomy"
                    )
            normalized_keywords = [
                keyword.strip().casefold() for keyword in classification_rule.keywords
            ]
            if any(not keyword for keyword in normalized_keywords):
                raise ValueError(f"classification.rules[{index}].keywords cannot contain blanks")
            if seen_keywords.intersection(normalized_keywords):
                raise ValueError("classification rule keywords must be unique")
            seen_keywords.update(normalized_keywords)

        routing_ids = [routing_rule.id for routing_rule in self.routing]
        if any(not rule_id.strip() for rule_id in routing_ids):
            raise ValueError("routing rule ids cannot be blank")
        if len(routing_ids) != len(set(routing_ids)):
            raise ValueError("routing rule ids must be unique")
        for index, routing_rule in enumerate(self.routing):
            if routing_rule.when is None:
                continue
            for dimension, allowed in taxonomy.items():
                value = getattr(routing_rule.when, dimension)
                if value is not None and value not in allowed:
                    raise ValueError(
                        f"routing[{index}].when.{dimension}={value!r} is not-in-taxonomy"
                    )
        return self
