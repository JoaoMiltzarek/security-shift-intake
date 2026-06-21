"""M2.c: tests for messiness injection.

Verifies: ground truth is preserved, output is deterministic, documented rates
hold over a large sample, and individual ops behave correctly.
"""

from __future__ import annotations

import random

from data.generators import messiness
from data.generators.messiness import SurfaceText, inject_messiness
from data.generators.records import generate_record


def _rng(seed: int = 0) -> random.Random:
    return random.Random(seed)


# ---------------------------------------------------------------------------
# Ground truth preservation + determinism
# ---------------------------------------------------------------------------


def test_record_not_mutated() -> None:
    rec = generate_record(_rng(1), "r0")
    before = rec.model_copy(deep=True)
    inject_messiness(_rng(2), rec)
    assert rec == before


def test_same_seed_same_surface() -> None:
    rec = generate_record(_rng(5), "r0")
    s1 = inject_messiness(_rng(9), rec)
    s2 = inject_messiness(_rng(9), rec)
    assert s1 == s2


def test_output_is_surface_text() -> None:
    rec = generate_record(_rng(3), "r0")
    surface = inject_messiness(_rng(3), rec)
    assert isinstance(surface, SurfaceText)
    assert surface.record_id == rec.record_id


# ---------------------------------------------------------------------------
# Individual ops behave correctly
# ---------------------------------------------------------------------------


def test_ambiguous_swap_changes_only_lookalikes() -> None:
    text = "10/01/2026"
    swapped, changed = messiness._ambiguous_swap(_rng(0), text)
    assert changed
    # Same length, differs in exactly one position, and that char is a known pair.
    assert len(swapped) == len(text)
    diffs = [(a, b) for a, b in zip(text, swapped, strict=True) if a != b]
    assert len(diffs) == 1
    a, b = diffs[0]
    assert messiness._AMBIGUOUS[a] == b


def test_abbreviate_replaces_known_form() -> None:
    out, changed = messiness._abbreviate("Portaria 1")
    assert changed
    assert "Port." in out


def test_abbreviate_noop_when_no_match() -> None:
    out, changed = messiness._abbreviate("xyz 1")
    assert not changed
    assert out == "xyz 1"


def test_misspell_keeps_length_and_words() -> None:
    text = "tentativa de acesso indevido"
    out, changed = messiness._misspell(_rng(1), text)
    assert changed
    assert len(out) == len(text)  # adjacent swap preserves length
    assert len(out.split()) == len(text.split())


def test_crossout_marker_present() -> None:
    out, changed = messiness._crossout(_rng(1), "acesso indevido")
    assert changed
    assert messiness.CROSSOUT_OPEN in out


def test_partial_shortens_text() -> None:
    text = "uma descricao bem longa com varias palavras aqui"
    out, changed = messiness._partial(_rng(1), text)
    assert changed
    assert len(out.split()) < len(text.split())


# ---------------------------------------------------------------------------
# Documented rates hold over a large sample
# ---------------------------------------------------------------------------


def test_blank_optional_rate_within_tolerance() -> None:
    rng = _rng(2026)
    # Only records WITH a description can be blanked — count among those.
    eligible = 0
    blanked = 0
    for i in range(4000):
        rec = generate_record(rng, f"r{i}")
        if rec.incident_description is None:
            continue
        eligible += 1
        surface = inject_messiness(rng, rec)
        if "blank:description" in surface.applied:
            blanked += 1
    assert eligible > 200
    rate = blanked / eligible
    assert abs(rate - messiness.P_BLANK_OPTIONAL) < 0.03


def test_some_messiness_is_applied_overall() -> None:
    rng = _rng(11)
    any_applied = 0
    total = 3000
    for i in range(total):
        rec = generate_record(rng, f"r{i}")
        surface = inject_messiness(rng, rec)
        if surface.applied:
            any_applied += 1
    # A meaningful fraction of records should carry at least one messiness op.
    assert any_applied / total > 0.15
