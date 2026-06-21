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

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Field types the pipeline supports
# ---------------------------------------------------------------------------

FieldType = Literal["date", "string", "enum", "bool", "text"]


class FieldSchema(BaseModel):
    """Schema for a single field in the handwritten report form."""

    name: str
    type: FieldType
    required: bool = True
    handwritten: bool = True
    # Only meaningful when type == "enum"; must be provided in that case.
    values: list[str] | None = None

    @model_validator(mode="after")
    def enum_requires_values(self) -> FieldSchema:
        if self.type == "enum" and not self.values:
            raise ValueError(
                f"Field '{self.name}': type='enum' requires a non-empty 'values' list."
            )
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
# Top-level config document
# ---------------------------------------------------------------------------


class ReportConfig(BaseModel):
    """The complete config document loaded from a configs/*.yaml file.

    Validates the whole structure: field definitions, taxonomy, routing rules,
    and the email template path.
    """

    report_type: str
    fields: Annotated[list[FieldSchema], Field(min_length=1)]
    classification: ClassificationConfig
    routing: list[RoutingRule]
    email_template: str

    @model_validator(mode="after")
    def routing_has_default(self) -> ReportConfig:
        """At least one routing rule must be the catch-all (when=None)."""
        has_default = any(r.when is None for r in self.routing)
        if not has_default:
            raise ValueError(
                "routing must include at least one default rule (when: null / omitted)."
            )
        return self
