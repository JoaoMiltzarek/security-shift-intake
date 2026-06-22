"""Transcription baseline eval: Tesseract OCR on Tier B, CER/WER vs ground truth.

This is the classical-OCR baseline that the VLM must beat to earn its cost
(spec §6). The VLM's own CER/WER requires a live API and is reported as pending
until a key exists (mock-first). If the tesseract binary is not installed, this
eval reports `available: false` rather than fabricating a number.

Ground truth = the handwritten surface values rendered on the page; the printed
labels are also on the page, so this is a directional baseline. And per §4,
font-handwriting is easier than real handwriting → an optimistic upper bound.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytesseract

from data.generators.tier_b import TierBGroundTruth, build_tier_b
from evals.metrics import cer, wer
from src.pipeline.ingest import rasterize_pdf

_SURFACE_FIELDS = (
    "shift_date_text",
    "guard_name_text",
    "post_text",
    "shift_period_text",
    "incident_occurred_text",
    "incident_description_text",
)


def tesseract_available() -> bool:
    """True if the tesseract binary is callable."""
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:  # noqa: BLE001 — any failure means unavailable
        return False


def ground_truth_text(gt: TierBGroundTruth) -> str:
    """The handwritten content as a human would transcribe it (values, in order)."""
    surface = gt.surface.model_dump()
    parts = [str(surface[f]) for f in _SURFACE_FIELDS if surface.get(f)]
    return " ".join(parts)


def run(seed: int = 1, n: int = 5, dpi: int = 200) -> dict[str, Any]:
    """Run the Tesseract baseline over a small Tier B set. Graceful if unavailable."""
    if not tesseract_available():
        return {
            "component": "transcription_baseline_tesseract",
            "available": False,
            "reason": "tesseract binary not installed",
        }

    cers: list[float] = []
    wers: list[float] = []
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        build_tier_b(out_dir=out, seed=seed, n=n, dpi=dpi)
        for line in (out / "ground_truth.jsonl").read_text(encoding="utf-8").splitlines():
            gt = TierBGroundTruth.model_validate_json(line)
            image = rasterize_pdf(out / "pdfs" / gt.pdf, dpi=dpi)[0]
            ocr = pytesseract.image_to_string(image).strip()
            reference = ground_truth_text(gt)
            cers.append(cer(reference, ocr))
            wers.append(wer(reference, ocr))

    return {
        "component": "transcription_baseline_tesseract",
        "available": True,
        "n": n,
        "mean_cer": sum(cers) / len(cers),
        "mean_wer": sum(wers) / len(wers),
        "caveat": (
            "Directional baseline: OCR sees printed labels too, and font-handwriting "
            "is easier than real handwriting (optimistic upper bound, spec §4)."
        ),
    }
