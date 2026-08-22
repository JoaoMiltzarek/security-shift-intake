"""Pydantic models for the report-type configuration (the YAML schema).

This is the executable schema for the single table contract supported by v1.
Every YAML value is validated before startup; a future report type requires an
explicit product and parser change, not just another file.

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

_SUPPORTED_REPORT_TYPE = "controle_ocorrencias"
_SUPPORTED_FIELDS = [
    ("data_turno", "string", True),
    ("vigilantes", "string", True),
    ("unidade", "string", True),
    ("ocorrencias", "table", False),
]
_SUPPORTED_COLUMNS = [
    ("item", "string"),
    ("hora", "string"),
    ("descricao", "text"),
    ("acao", "string"),
    ("resolvido", "enum"),
]


def _validate_identifiers(values: list[str], location: str) -> None:
    stripped = [value.strip() for value in values]
    if any(not value for value in stripped):
        raise ValueError(f"{location} cannot contain blanks")
    if values != stripped:
        raise ValueError(f"{location} cannot contain surrounding whitespace")
    if len(stripped) != len({value.casefold() for value in stripped}):
        raise ValueError(f"{location} must be unique")


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
    # (e.g. ["Data", "Dia"]). Optional within the supported table contract.
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

    @model_validator(mode="after")
    def require_at_least_one_constraint(self) -> RoutingCondition:
        if self.type is None and self.urgency is None and self.sector is None:
            raise ValueError("routing when condition cannot be empty")
        return self


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
        _validate_identifiers([self.report_type], "report_type")

        field_names = [field.name for field in self.fields]
        _validate_identifiers(field_names, "field names")

        table_fields = [field for field in self.fields if field.type == "table"]
        if len(table_fields) != 1:
            raise ValueError("v1 requires exactly one table field per report config")
        for table in table_fields:
            column_names = [column.name for column in table.columns or []]
            _validate_identifiers(column_names, f"table '{table.name}' column names")

        field_surface = [(field.name, field.type, field.required) for field in self.fields]
        table = table_fields[0]
        column_surface = [(column.name, column.type) for column in table.columns or []]
        resolved = next(
            (column for column in table.columns or [] if column.name == "resolvido"), None
        )
        if (
            self.report_type != _SUPPORTED_REPORT_TYPE
            or field_surface != _SUPPORTED_FIELDS
            or column_surface != _SUPPORTED_COLUMNS
            or resolved is None
            or resolved.values != ["sim", "nao"]
        ):
            raise ValueError(
                "v1 supports only the controle_ocorrencias table contract "
                "with its canonical header and columns"
            )

        default_indexes = [index for index, rule in enumerate(self.routing) if rule.when is None]
        if default_indexes != [len(self.routing) - 1]:
            raise ValueError("routing must contain exactly one default rule and it must be last")

        taxonomy = {
            "type": set(self.classification.type.labels),
            "urgency": set(self.classification.urgency.labels),
            "sector": set(self.classification.sector.labels),
        }
        for dimension in taxonomy:
            configured = getattr(self.classification, dimension).labels
            _validate_identifiers(configured, f"classification.{dimension}.labels")

        classification_ids = [
            classification_rule.id for classification_rule in self.classification.rules
        ]
        _validate_identifiers(classification_ids, "classification rule ids")
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
        _validate_identifiers(routing_ids, "routing rule ids")
        prior_conditions: list[tuple[int, dict[str, str]]] = []
        for index, routing_rule in enumerate(self.routing):
            _validate_identifiers(routing_rule.recipients, f"routing[{index}].recipients")
            if routing_rule.when is None:
                continue
            condition = {
                dimension: value
                for dimension in taxonomy
                if (value := getattr(routing_rule.when, dimension)) is not None
            }
            for dimension, allowed in taxonomy.items():
                value = condition.get(dimension)
                if value is not None and value not in allowed:
                    raise ValueError(
                        f"routing[{index}].when.{dimension}={value!r} is not-in-taxonomy"
                    )
            for prior_index, prior in prior_conditions:
                if prior.items() <= condition.items():
                    raise ValueError(
                        f"routing[{index}] is shadowed by earlier routing[{prior_index}]"
                    )
            prior_conditions.append((index, condition))
        return self
