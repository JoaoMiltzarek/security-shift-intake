"""M4.a: tests for PDF rasterization and base64 encoding.

Uses a real Tier B PDF built into tmp_path so the round-trip (render -> PDF ->
rasterize) is exercised exactly as the production path will run it.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from PIL import Image

from data.generators.tier_b import build_tier_b
from src.pipeline.ingest import DEFAULT_DPI, image_to_base64_png, rasterize_pdf


@pytest.fixture(scope="module")
def sample_pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("tier_b")
    build_tier_b(out_dir=out, seed=1, n=1, dpi=150)
    return next((out / "pdfs").glob("*.pdf"))


def test_rasterize_returns_one_image_per_page(sample_pdf: Path) -> None:
    images = rasterize_pdf(sample_pdf, dpi=150)
    assert len(images) == 1
    assert isinstance(images[0], Image.Image)


def test_rasterized_image_is_rgb_and_nonempty(sample_pdf: Path) -> None:
    img = rasterize_pdf(sample_pdf, dpi=150)[0]
    assert img.mode == "RGB"
    assert img.width > 100 and img.height > 100


def test_higher_dpi_yields_larger_image(sample_pdf: Path) -> None:
    low = rasterize_pdf(sample_pdf, dpi=100)[0]
    high = rasterize_pdf(sample_pdf, dpi=200)[0]
    assert high.width > low.width
    assert high.height > low.height


def test_default_dpi_is_250() -> None:
    assert DEFAULT_DPI == 250


def test_missing_pdf_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        rasterize_pdf(tmp_path / "nope.pdf")


def test_base64_png_round_trips(sample_pdf: Path) -> None:
    img = rasterize_pdf(sample_pdf, dpi=100)[0]
    b64 = image_to_base64_png(img)
    raw = base64.standard_b64decode(b64)
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic bytes
