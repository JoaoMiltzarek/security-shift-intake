"""M3.d (DoD): Tier B produces PDFs + ground_truth.jsonl that round-trip.

Verifies the full record -> surface -> render -> degrade -> PDF path, the ground
truth tying each PDF to its truth, determinism, and that a produced PDF can be
rasterized back to an image (the real ingest path, exercised in M4).
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pymupdf
import pytest

from data.generators.tier_b import (
    TierBGroundTruth,
    build_tier_b,
    generate_document,
)

# ---------------------------------------------------------------------------
# Single document
# ---------------------------------------------------------------------------


def test_generate_document_returns_image_and_truth() -> None:
    img, gt = generate_document(random.Random(0), "doc-00000")
    assert img.size[0] > 0 and img.size[1] > 0
    assert isinstance(gt, TierBGroundTruth)
    assert gt.pdf == "doc-00000.pdf"
    # Ground truth ties clean record + messy surface to the same id.
    assert gt.record.record_id == "doc-00000"
    assert gt.surface.record_id == "doc-00000"


def test_generate_document_is_deterministic() -> None:
    a_img, a_gt = generate_document(random.Random(5), "doc-1")
    b_img, b_gt = generate_document(random.Random(5), "doc-1")
    assert a_img.tobytes() == b_img.tobytes()
    assert a_gt == b_gt


# ---------------------------------------------------------------------------
# Full build (DoD)
# ---------------------------------------------------------------------------


def test_build_tier_b_creates_pdfs_and_ground_truth(tmp_path: Path) -> None:
    out = tmp_path / "tier_b"
    meta = build_tier_b(out_dir=out, seed=7, n=5, dpi=150)

    pdfs = sorted((out / "pdfs").glob("*.pdf"))
    assert len(pdfs) == 5
    assert meta.n == 5
    assert (out / "meta.json").exists()

    # ground_truth.jsonl has one valid entry per PDF.
    lines = (out / "ground_truth.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    gts = [TierBGroundTruth.model_validate_json(line) for line in lines]
    gt_pdfs = {gt.pdf for gt in gts}
    assert gt_pdfs == {p.name for p in pdfs}


def test_ground_truth_has_both_views(tmp_path: Path) -> None:
    out = tmp_path / "tier_b"
    build_tier_b(out_dir=out, seed=1, n=3, dpi=150)
    line = (out / "ground_truth.jsonl").read_text(encoding="utf-8").splitlines()[0]
    data = json.loads(line)
    # Clean record fields (extraction truth) and surface text (transcription truth).
    assert "record" in data and "incident_type" in data["record"]
    assert "surface" in data and "shift_date_text" in data["surface"]


def test_pdf_round_trips_to_image(tmp_path: Path) -> None:
    out = tmp_path / "tier_b"
    build_tier_b(out_dir=out, seed=2, n=1, dpi=150)
    pdf_path = next((out / "pdfs").glob("*.pdf"))

    doc = pymupdf.open(pdf_path)
    assert doc.page_count == 1
    pix = doc[0].get_pixmap(dpi=150)
    assert pix.width > 100 and pix.height > 100
    doc.close()


def test_samples_written_when_requested(tmp_path: Path) -> None:
    out = tmp_path / "tier_b"
    samples = tmp_path / "samples"
    build_tier_b(out_dir=out, seed=3, n=4, dpi=150, n_samples=2, samples_dir=samples)
    pngs = sorted(samples.glob("*.png"))
    assert len(pngs) == 2


def test_build_rejects_zero_n(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        build_tier_b(out_dir=tmp_path, seed=0, n=0)
