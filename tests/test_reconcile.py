"""Tests for src/pipeline/reconcile.py — deterministic field arbitration.

Named invariants (per plan F3):
- test_critical_field_disagree_never_auto_resolved
- test_critical_field_agree_confidence_high_not_certain
- test_justification_always_nonempty
"""

from __future__ import annotations

from src.pipeline.reconcile import (
    CRITICAL_FIELDS,
    ReconcileResult,
    reconcile_field,
    reconcile_sheet,
)

# ---------------------------------------------------------------------------
# reconcile_field — basic cases
# ---------------------------------------------------------------------------


def test_both_agree_returns_consensus() -> None:
    r = reconcile_field("descricao", "ambulância", "ambulância")
    assert r.source == "consensus"
    assert r.value == "ambulância"
    assert r.confidence == "HIGH"


def test_both_blank_returns_consensus_blank() -> None:
    r = reconcile_field("descricao", None, None)
    assert r.source == "consensus"
    assert r.value is None
    assert r.justification == "both_readers_blank"


def test_noncritical_disagree_prefers_vlm() -> None:
    r = reconcile_field("descricao", "ambulancia", "ambulância")
    assert r.source == "vlm_preferred"
    assert r.value == "ambulância"
    assert r.confidence == "MEDIUM"


def test_noncritical_disagree_ocr_fallback_when_vlm_blank() -> None:
    r = reconcile_field("descricao", "ambulância", None)
    assert r.source == "vlm_preferred"
    assert r.value == "ambulância"  # falls back to ocr when vlm is None


# ---------------------------------------------------------------------------
# Named invariants: critical fields
# ---------------------------------------------------------------------------


def test_critical_field_disagree_never_auto_resolved() -> None:
    """Critical field with differing values must never be auto-resolved."""
    for field in ("hora", "unidade", "vigilantes", "data_turno"):
        r = reconcile_field(field, "valor_ocr", "valor_vlm")
        assert r.source == "human_required", f"field={field}: got source={r.source!r}"
        assert r.value is None, f"field={field}: value must be None, got {r.value!r}"


def test_critical_field_agree_confidence_high_not_certain() -> None:
    """Critical field with agreeing values: confidence capped at HIGH, never CERTAIN."""
    for field in CRITICAL_FIELDS:
        r = reconcile_field(field, "turno noite", "turno noite")
        assert r.confidence == "HIGH", f"field={field}: got {r.confidence!r}"
        assert r.confidence != "CERTAIN"
        assert r.source == "consensus"


def test_justification_always_nonempty() -> None:
    """Every reconcile_field call must produce a non-empty justification."""
    cases: list[tuple[str, str | None, str | None]] = [
        ("hora", "10:00", "10:00"),
        ("hora", "10:00", "11:00"),
        ("descricao", "abc", "xyz"),
        ("descricao", None, None),
        ("descricao", "abc", None),
        ("hora", None, "10:00"),
    ]
    for field, ocr, vlm in cases:
        r = reconcile_field(field, ocr, vlm)
        assert r.justification, (
            f"empty justification for field={field!r}, ocr={ocr!r}, vlm={vlm!r}"
        )


# ---------------------------------------------------------------------------
# is_critical override
# ---------------------------------------------------------------------------


def test_is_critical_override_false_allows_auto_resolve() -> None:
    r = reconcile_field("hora", "10:00", "11:00", is_critical=False)
    assert r.source == "vlm_preferred"
    assert r.value == "11:00"


def test_is_critical_override_true_blocks_noncritical_field() -> None:
    r = reconcile_field("descricao", "abc", "xyz", is_critical=True)
    assert r.source == "human_required"
    assert r.value is None


# ---------------------------------------------------------------------------
# reconcile_sheet
# ---------------------------------------------------------------------------


def test_reconcile_sheet_returns_one_result_per_field() -> None:
    extractions = {
        "data_turno": ("14/03 Noite", "14/03 Noite"),
        "vigilantes": ("B. Lima", "C. Souza"),
        "descricao": ("ambulância", "ambulância"),
    }
    results = reconcile_sheet(extractions)
    assert len(results) == 3
    assert [r.field for r in results] == ["data_turno", "vigilantes", "descricao"]


def test_reconcile_sheet_critical_disagree_stays_unresolved() -> None:
    results = reconcile_sheet({"hora": ("10:00", "11:00")})
    assert results[0].source == "human_required"
    assert results[0].value is None


def test_reconcile_sheet_custom_critical_fields() -> None:
    custom = frozenset({"descricao"})
    extractions = {"descricao": ("abc", "xyz"), "hora": ("10:00", "11:00")}
    results = reconcile_sheet(extractions, critical_fields=custom)
    by_field = {r.field: r for r in results}
    assert by_field["descricao"].source == "human_required"
    assert by_field["hora"].source == "vlm_preferred"


def test_reconcile_sheet_empty_input() -> None:
    assert reconcile_sheet({}) == []


def test_reconcile_result_is_namedtuple() -> None:
    r = reconcile_field("unidade", "U01", "U01")
    assert isinstance(r, ReconcileResult)
    assert hasattr(r, "field")
    assert hasattr(r, "justification")
