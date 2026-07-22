"""Phase 2 eval: real Brazilian-Portuguese handwriting (BRESSAY), Tesseract vs VLM.

This is the meaningful HTR eval the project was missing: instead of only the
synthetic Tier B (font-handwriting, an "optimistic upper bound", spec §4), it
measures CER/WER on **real** handwriting from BRESSAY — a Brazilian-Portuguese
offline-HTR dataset (ICDAR 2024) whose challenges (crossed-out text, erasures,
smudges, varied hands) match the real occurrence sheets. See docs/EVAL_BRESSAY.md
to obtain it; it is NOT vendored (it is third-party data, and large).

Honesty, same as the rest of the harness:
- Graceful when unavailable: if the dataset/manifest is missing it reports
  `available: false` rather than fabricating a number (spec §8.7).
- Always reports the Tesseract baseline next to the VLM, so the VLM has to *earn*
  its place (spec §6).
- Domain caveat: BRESSAY is student essays; security forms differ in vocabulary
  and layout. Treat these as directional and also measure on your curated sheets.

Run: `make eval-bressay` (or `python -m evals.eval_htr_bressay --n 50`). Needs a
local VLM server for the VLM column (see docs/EVAL_BRESSAY.md); the baseline column
needs only Tesseract.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from evals.eval_transcription import tesseract_available
from evals.metrics import cer, wer
from src.clients.base import DocumentReader
from src.clients.factory import get_vision_client
from src.clients.local_ocr import LocalOCRVisionClient
from src.pipeline.ingest import Deadline, load_page_artifacts

DEFAULT_DATASET_DIR = Path(os.environ.get("BRESSAY_DIR", "datasets/bressay"))
MANIFEST_NAME = "manifest.jsonl"


def load_manifest(dataset_dir: Path) -> list[tuple[Path, str]]:
    """Read (image_path, reference_text) pairs from <dataset_dir>/manifest.jsonl.

    Each line: {"image": "<path, abs or relative to dataset_dir>", "text": "..."}.
    See docs/EVAL_BRESSAY.md for how to generate it from the BRESSAY release.
    """
    manifest = dataset_dir / MANIFEST_NAME
    pairs: list[tuple[Path, str]] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        image = Path(row["image"])
        if not image.is_absolute():
            image = dataset_dir / image
        pairs.append((image, str(row["text"])))
    return pairs


def _score_client(client: DocumentReader, pairs: list[tuple[Path, str]]) -> dict[str, Any]:
    """Run a document reader over the pairs and return mean CER/WER."""
    cers: list[float] = []
    wers: list[float] = []
    for image_path, reference in pairs:
        deadline = Deadline.after(300.0)
        (page,) = load_page_artifacts(image_path, deadline=deadline)
        hypothesis = client.read(page, deadline).text
        cers.append(cer(reference, hypothesis))
        wers.append(wer(reference, hypothesis))
    return {
        "available": True,
        "n": len(pairs),
        "mean_cer": sum(cers) / len(cers),
        "mean_wer": sum(wers) / len(wers),
    }


def run(
    dataset_dir: Path = DEFAULT_DATASET_DIR,
    n: int = 50,
    vision_name: str = "local_vlm",
) -> dict[str, Any]:
    """Score Tesseract (baseline) and the chosen VLM on up to *n* BRESSAY samples."""
    manifest = dataset_dir / MANIFEST_NAME
    if not manifest.exists():
        return {
            "component": "htr_bressay",
            "available": False,
            "reason": (
                f"BRESSAY manifest not found at {manifest}. "
                "See docs/EVAL_BRESSAY.md to download the dataset and build it."
            ),
        }

    pairs = load_manifest(dataset_dir)[:n]
    if not pairs:
        return {"component": "htr_bressay", "available": False, "reason": "empty manifest"}

    result: dict[str, Any] = {
        "component": "htr_bressay",
        "available": True,
        "n_requested": n,
        "n_used": len(pairs),
        "caveat": (
            "Real BR-PT handwriting (BRESSAY, ICDAR 2024). Domain gap: student essays, "
            "not occurrence forms — directional; also measure on curated real sheets."
        ),
    }

    # Baseline column (Tesseract) — graceful if the binary is absent.
    if tesseract_available():
        result["baseline_tesseract"] = _score_client(LocalOCRVisionClient(), pairs)
    else:
        result["baseline_tesseract"] = {"available": False, "reason": "tesseract not installed"}

    # VLM column — graceful if no local server is reachable (no fabricated number).
    try:
        client = get_vision_client(vision_name)
        result["vlm"] = {"model": vision_name, **_score_client(client, pairs)}
    except RuntimeError as exc:
        result["vlm"] = {"model": vision_name, "available": False, "reason": str(exc)}

    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="BRESSAY HTR eval: Tesseract vs local VLM.")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--n", type=int, default=50, help="max samples to score")
    parser.add_argument("--vision", default="local_vlm", help="INTAKE_VISION client for the VLM")
    args = parser.parse_args(argv)

    result = run(dataset_dir=args.dataset_dir, n=args.n, vision_name=args.vision)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("available") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
