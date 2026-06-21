"""Tier B orchestration: clean record -> messy surface -> rendered form -> scanned
PDF, plus a ground_truth.jsonl tying each PDF back to its truth.

Two ground-truth views are persisted per document:
  - record:  the CLEAN structured truth (for the extraction & classification eval)
  - surface: the messy text actually drawn on the page (for the transcription eval)

Each document is generated from its own per-document RNG so the whole Tier B set is
deterministic and individually reproducible.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from PIL import Image
from pydantic import BaseModel

from data.generators.degrade import degrade_scan
from data.generators.messiness import SurfaceText, inject_messiness
from data.generators.records import SyntheticRecord, generate_record
from data.generators.render import render_form

DATASET_VERSION = "tier_b/v1"
DEFAULT_DPI = 200


class TierBGroundTruth(BaseModel):
    """Ground truth for one rendered document."""

    pdf: str
    record: SyntheticRecord
    surface: SurfaceText


class TierBMeta(BaseModel):
    version: str
    seed: int
    n: int
    dpi: int


def _doc_rng(seed: int, index: int) -> random.Random:
    """Independent, reproducible RNG per document."""
    return random.Random(seed * 1_000_003 + index)


def generate_document(rng: random.Random, doc_id: str) -> tuple[Image.Image, TierBGroundTruth]:
    """Produce a scan-degraded image and its ground truth for one document."""
    record = generate_record(rng, doc_id)
    surface = inject_messiness(rng, record)
    clean = render_form(rng, surface)
    degraded = degrade_scan(rng, clean)
    gt = TierBGroundTruth(pdf=f"{doc_id}.pdf", record=record, surface=surface)
    return degraded, gt


def save_image_as_pdf(image: Image.Image, path: Path, dpi: int = DEFAULT_DPI) -> None:
    """Save a single-page PDF (mimics the printer-scan -> PDF path)."""
    image.save(path, "PDF", resolution=float(dpi))


def build_tier_b(
    out_dir: Path,
    seed: int,
    n: int,
    dpi: int = DEFAULT_DPI,
    n_samples: int = 0,
    samples_dir: Path | None = None,
) -> TierBMeta:
    """Generate *n* documents (PDFs + ground_truth.jsonl). Optionally write PNG samples."""
    if n <= 0:
        raise ValueError("n must be positive")

    pdf_dir = out_dir / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    if samples_dir is not None and n_samples > 0:
        samples_dir.mkdir(parents=True, exist_ok=True)

    gt_path = out_dir / "ground_truth.jsonl"
    with gt_path.open("w", encoding="utf-8") as fh:
        for i in range(n):
            rng = _doc_rng(seed, i)
            image, gt = generate_document(rng, f"doc-{i:05d}")
            save_image_as_pdf(image, pdf_dir / gt.pdf, dpi=dpi)
            fh.write(json.dumps(gt.model_dump(mode="json"), ensure_ascii=False))
            fh.write("\n")
            if samples_dir is not None and i < n_samples:
                image.save(samples_dir / f"sample_{gt.pdf.replace('.pdf', '.png')}")

    meta = TierBMeta(version=DATASET_VERSION, seed=seed, n=n, dpi=dpi)
    (out_dir / "meta.json").write_text(
        json.dumps(meta.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return meta
