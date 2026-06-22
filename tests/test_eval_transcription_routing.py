"""M8.c: Tesseract baseline (graceful) + routing eval."""

from __future__ import annotations

import random

from data.generators.messiness import inject_messiness
from data.generators.records import generate_record
from data.generators.tier_b import TierBGroundTruth
from evals import eval_routing, eval_transcription

# --- Tesseract baseline ---


def test_tesseract_available_returns_bool() -> None:
    assert isinstance(eval_transcription.tesseract_available(), bool)


def test_run_is_graceful_without_binary() -> None:
    # Returns a structured result whether or not tesseract is installed.
    result = eval_transcription.run(seed=1, n=2)
    assert result["component"] == "transcription_baseline_tesseract"
    assert isinstance(result["available"], bool)
    if not result["available"]:
        assert "reason" in result
    else:
        assert result["mean_cer"] >= 0.0
        assert result["mean_wer"] >= 0.0


def test_ground_truth_text_joins_surface_values() -> None:
    rng = random.Random(0)
    rec = generate_record(rng, "doc-0")
    surface = inject_messiness(rng, rec)
    gt = TierBGroundTruth(pdf="doc-0.pdf", record=rec, surface=surface)
    text = eval_transcription.ground_truth_text(gt)
    assert surface.guard_name_text in text
    assert surface.shift_date_text in text


# --- Routing eval ---


def test_routing_eval_is_perfect() -> None:
    result = eval_routing.run()
    assert result["component"] == "routing"
    assert result["accuracy"] == 1.0
    assert result["mismatches"] == []


def test_routing_eval_detects_mismatch(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Inject a wrong expectation and confirm the eval flags it (proves it's a real check).
    bad = list(eval_routing._EXPECTATIONS)
    bad[0] = (("safety", "critical", "facilities"), ["wrong_recipient"])
    monkeypatch.setattr(eval_routing, "_EXPECTATIONS", bad)
    result = eval_routing.run()
    assert result["accuracy"] < 1.0
    assert len(result["mismatches"]) == 1
