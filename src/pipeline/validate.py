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
from typing import Any

from src.schema.config import FieldSchema, ReportConfig
from src.schema.extraction import AuditedField
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
            # optional + blank -> fine: no value to be (un)confident about, no flag
        else:
            err = _type_error(field, str(extracted.value))
            if err is not None:
                errors.append(err)
                flagged = True
            if extracted.confidence < threshold:
                flagged = True  # low-confidence value -> review (not a schema error)

        if flagged:
            must_review.append(field.name)

        status = (
            "missing" if _is_blank(extracted.value)
            else ("must_review" if flagged else "accepted")
        )
        updated.append(extracted.model_copy(update={"must_review": flagged, "status": status}))

    return state.model_copy(
        update={
            "extracted_fields": updated,
            "must_review_fields": must_review,
            "validation_errors": errors,
        }
    )


def validate_table(
    state: PipelineState,
    config: ReportConfig,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> PipelineState:
    """Critic for the table path: flatten Raw header + Normalized occurrences into
    `extracted_fields` with MUST_REVIEW flags (so the review UI / draft / gate work).

    A header cell is flagged when required-but-blank, or its `status` != accepted, or
    confidence < threshold. Each occurrence becomes one field flagged by `needs_review`.
    `S/A` sheets yield a single, non-flagged "(sem alteração)" field — never an incident.
    """
    raw = state.raw_extraction
    normalized = state.normalized
    if raw is None or normalized is None:
        raise ValueError("validate_table() requires raw_extraction and normalized in state.")

    fields: list[ExtractedField] = []
    must_review: list[str] = []
    errors: list[str] = []

    for field in config.fields:
        if field.type == "table":
            continue
        cell: AuditedField | None = getattr(raw.header, field.name, None)
        value: Any = cell.value if cell is not None else None
        confidence = cell.confidence if cell is not None else 0.0
        flagged = False
        if _is_blank(value):
            if field.required:
                errors.append(f"{field.name}: required field is missing")
                flagged = True
        elif (cell is not None and cell.status != "accepted") or confidence < threshold:
            flagged = True
        status = "missing" if _is_blank(value) else ("must_review" if flagged else "accepted")
        fields.append(
            ExtractedField(
                name=field.name,
                value=value,
                confidence=confidence,
                must_review=flagged,
                source=cell.source if cell is not None else None,
                status=status,
            )
        )
        if flagged:
            must_review.append(field.name)

    if normalized.no_occurrence:
        fields.append(
            ExtractedField(
                name="ocorrencias", value="(sem alteração)", confidence=1.0, must_review=False,
                source="rule", status="accepted",
            )
        )
    else:
        for i, occ in enumerate(normalized.occurrences, start=1):
            # OBJETO (item) — ambiguous/blank must block export (R: "nunca adivinhar").
            obj_name = f"ocorrencia_{i}_objeto"
            obj_blank = occ.category is None or not str(occ.category).strip()
            obj_flag = obj_blank or occ.needs_review
            fields.append(
                ExtractedField(
                    name=obj_name,
                    value=occ.category or "(revisar)",
                    confidence=0.0 if obj_blank else (0.4 if obj_flag else 1.0),
                    must_review=obj_flag,
                    source="rule",
                    status=(
                        "missing" if obj_blank else ("must_review" if obj_flag else "accepted")
                    ),
                )
            )
            if obj_flag:
                must_review.append(obj_name)
            # DESCRIÇÃO.
            desc_name = f"ocorrencia_{i}"
            desc_flag = occ.needs_review
            fields.append(
                ExtractedField(
                    name=desc_name,
                    value=occ.description or "(sem descrição)",
                    confidence=0.4 if desc_flag else 1.0,
                    must_review=desc_flag,
                    source="rule",
                    status="must_review" if desc_flag else "accepted",
                )
            )
            if desc_flag:
                must_review.append(desc_name)

    return state.model_copy(
        update={
            "extracted_fields": fields,
            "must_review_fields": must_review,
            "validation_errors": errors,
        }
    )
