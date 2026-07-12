"""Deterministic field reconciler — compares two reader outputs and arbitrates.

Status: EXPERIMENTAL two-reader arbitration prototype, outside v1. No supported entrypoint
invokes this module; unit tests cover its standalone semantics only.

Design rules (CLAUDE.md invariants):
- Zero ML imports: stdlib + typing only.
- Critical fields NEVER auto-resolved when readers disagree.
- `justification` is always a non-empty string.
- Confidence is capped at "HIGH" even when readers agree (never "CERTAIN").

It is a reserved design experiment for a future dual-reader pipeline, not evidence that the
current cockpit consumes reconciled fields.
"""

from __future__ import annotations

from typing import NamedTuple

# Fields whose values can never be auto-resolved when the two readers disagree.
# A wrong value in any of these goes directly to the human reviewer.
CRITICAL_FIELDS: frozenset[str] = frozenset(
    {
        "data_turno",
        "vigilantes",
        "unidade",
        "hora",
        "hora_entrada",
        "hora_saida",
        "item",  # tipo de ocorrência na tabela
    }
)

_Confidence = str  # "HIGH" | "MEDIUM" | "LOW"
_Source = str  # "consensus" | "vlm_preferred" | "human_required"


class ReconcileResult(NamedTuple):
    """Outcome of comparing two reader values for one field."""

    field: str
    value: str | None  # chosen value; None when human arbitration is required
    confidence: _Confidence
    source: _Source
    justification: str  # always non-empty; shown in the cockpit evidence block


def reconcile_field(
    field_name: str,
    ocr_val: str | None,
    vlm_val: str | None,
    is_critical: bool | None = None,
) -> ReconcileResult:
    """Compare one pair of reader values and return the arbitration result.

    Args:
        field_name: the schema field name (used to look up criticality by default).
        ocr_val: value produced by the OCR/rules reader.
        vlm_val: value produced by the VLM reader.
        is_critical: explicit override; if None, derived from CRITICAL_FIELDS.
    """
    critical = is_critical if is_critical is not None else (field_name in CRITICAL_FIELDS)

    ocr = ocr_val.strip() if ocr_val else None
    vlm = vlm_val.strip() if vlm_val else None

    if ocr == vlm:
        label = "both_readers_blank" if ocr is None else "both_readers_agree"
        return ReconcileResult(
            field=field_name,
            value=ocr,
            confidence="HIGH",
            source="consensus",
            justification=label,
        )

    # Readers disagree.
    if critical:
        return ReconcileResult(
            field=field_name,
            value=None,
            confidence="LOW",
            source="human_required",
            justification=f"readers_disagree_critical: ocr={ocr!r} vlm={vlm!r}",
        )

    chosen = vlm if vlm is not None else ocr
    return ReconcileResult(
        field=field_name,
        value=chosen,
        confidence="MEDIUM",
        source="vlm_preferred",
        justification=f"readers_disagree_noncritical: ocr={ocr!r} vlm={vlm!r}; vlm preferred",
    )


def reconcile_sheet(
    extractions: dict[str, tuple[str | None, str | None]],
    critical_fields: frozenset[str] | None = None,
) -> list[ReconcileResult]:
    """Reconcile all fields for one sheet.

    Args:
        extractions: mapping of field_name -> (ocr_value, vlm_value).
        critical_fields: override the default CRITICAL_FIELDS set; if None, uses module default.

    Returns one ReconcileResult per field, in iteration order of extractions.
    """
    effective_critical = critical_fields if critical_fields is not None else CRITICAL_FIELDS
    return [
        reconcile_field(
            field_name,
            ocr_val,
            vlm_val,
            is_critical=(field_name in effective_critical),
        )
        for field_name, (ocr_val, vlm_val) in extractions.items()
    ]
