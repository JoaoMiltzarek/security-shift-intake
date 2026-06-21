"""Stage 3 — Validate (critic): deterministic checks -> MUST_REVIEW flags.

The single most useful stage (spec §2): it catches type/required/allowed-value
violations and routes uncertainty (low confidence) to the human. All checks are
deterministic and live in code — not a second LLM.

A field is flagged MUST_REVIEW when any of these holds:
  - it is required but missing/blank,
  - its value is invalid for its type (bad date, unknown bool, out-of-set enum),
  - its confidence is below the review threshold.

`validation_errors` collects schema/type problems (not low confidence, which is a
review trigger rather than an error).
"""

from __future__ import annotations

from datetime import datetime

from src.schema.config import FieldSchema, ReportConfig
from src.schema.state import ExtractedField, PipelineState

# Confidence at/above which a field is trusted without review (spec §6: tune so
# real errors are flagged even at the cost of some extra human checks).
DEFAULT_CONFIDENCE_THRESHOLD = 0.70

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y")
_BOOL_TOKENS = {"sim", "nao", "não", "true", "false", "yes", "no", "s", "n", "1", "0"}


def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _type_error(field: FieldSchema, value: str) -> str | None:
    """Return an error message if *value* is invalid for the field's type, else None."""
    v = value.strip()
    if field.type == "date":
        for fmt in _DATE_FORMATS:
            try:
                datetime.strptime(v, fmt)
                return None
            except ValueError:
                continue
        return f"{field.name}: '{v}' is not a valid date"
    if field.type == "bool":
        if v.lower() not in _BOOL_TOKENS:
            return f"{field.name}: '{v}' is not a recognised boolean"
        return None
    if field.type == "enum":
        allowed = {a.lower() for a in (field.values or [])}
        if v.lower() not in allowed:
            return f"{field.name}: '{v}' not in allowed values {field.values}"
        return None
    # string / text: any non-blank value is acceptable.
    return None


def validate(
    state: PipelineState,
    config: ReportConfig,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> PipelineState:
    """Run the critic over the extracted fields; return state with MUST_REVIEW flags."""
    by_name = {f.name: f for f in state.extracted_fields}

    updated: list[ExtractedField] = []
    must_review: list[str] = []
    errors: list[str] = []

    for field in config.fields:
        extracted = by_name.get(field.name)
        if extracted is None:
            # Extract guarantees one entry per field; treat absence as missing.
            extracted = ExtractedField(name=field.name, value=None, confidence=0.0)

        flagged = False

        if _is_blank(extracted.value):
            if field.required:
                errors.append(f"{field.name}: required field is missing")
                flagged = True
            # optional + blank -> fine, no flag
        else:
            err = _type_error(field, str(extracted.value))
            if err is not None:
                errors.append(err)
                flagged = True

        if extracted.confidence < threshold:
            flagged = True  # low-confidence -> review (not a schema error)

        if flagged:
            must_review.append(field.name)

        updated.append(extracted.model_copy(update={"must_review": flagged}))

    return state.model_copy(
        update={
            "extracted_fields": updated,
            "must_review_fields": must_review,
            "validation_errors": errors,
        }
    )
