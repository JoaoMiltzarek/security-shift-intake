"""M4.a: tests for PDF rasterization and base64 encoding.

Uses a real Tier B PDF built into tmp_path so the round-trip (render -> PDF ->
rasterize) is exercised exactly as the production path will run it.
"""

from __future__ import annotations

import base64
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
import pytest
from PIL import Image

from data.generators.tier_b import build_tier_b
from src.pipeline import ingest
from src.pipeline.ingest import (
    DEFAULT_DPI,
    MAX_DPI,
    MAX_PAGES,
    IngestDocumentError,
    IngestLimitError,
    image_to_base64_png,
    load_source_images,
    rasterize_pdf,
)


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


@pytest.mark.parametrize(
    ("dpi", "expected_size"),
    [(72, (72, 36)), (150, (150, 75)), (250, (250, 125)), (300, (300, 150))],
)
def test_known_page_size_has_exact_dimensions_at_supported_dpi(
    tmp_path: Path, dpi: int, expected_size: tuple[int, int]
) -> None:
    source = tmp_path / "folha ç segurança.pdf"
    Image.new("RGB", (72, 36), "white").save(source, "PDF", resolution=72.0)

    image = rasterize_pdf(source, dpi=dpi)[0]

    assert image.size == expected_size
    assert image.mode == "RGB"


def test_multipage_pdf_is_rejected_for_the_single_page_v1_contract(tmp_path: Path) -> None:
    source = tmp_path / "multi page ç.pdf"
    red = Image.new("RGB", (60, 40), (240, 10, 10))
    blue = Image.new("RGB", (60, 40), (10, 10, 240))
    try:
        red.save(source, "PDF", resolution=72.0, save_all=True, append_images=[blue])
    finally:
        red.close()
        blue.close()

    with pytest.raises(IngestLimitError, match="single-page"):
        rasterize_pdf(source, dpi=72)


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


# --- load_source_images: PDF or image ---


def test_load_source_images_pdf(sample_pdf: Path) -> None:
    images = load_source_images(sample_pdf, dpi=120)
    assert len(images) == 1
    assert images[0].mode == "RGB"


def test_load_source_images_png(tmp_path: Path) -> None:
    png = tmp_path / "photo.png"
    Image.new("RGB", (50, 40), "white").save(png)
    images = load_source_images(png)
    assert len(images) == 1
    assert images[0].size == (50, 40)
    assert images[0].mode == "RGB"


def test_load_source_images_jpg(tmp_path: Path) -> None:
    jpg = tmp_path / "photo.jpg"
    Image.new("RGB", (30, 30), "white").save(jpg)
    assert len(load_source_images(jpg)) == 1


def test_load_source_images_rejects_unknown_type(tmp_path: Path) -> None:
    bad = tmp_path / "notes.txt"
    bad.write_text("hi", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported source type"):
        load_source_images(bad)


def test_load_source_images_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_source_images(tmp_path / "nope.pdf")


@pytest.mark.parametrize("dpi", [0, -1, MAX_DPI + 1])
def test_invalid_dpi_is_rejected_before_opening_source(
    tmp_path: Path, dpi: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"synthetic")
    monkeypatch.setattr(
        pdfium,
        "PdfDocument",
        lambda *args: pytest.fail("invalid DPI must fail before PDF parsing"),
    )
    with pytest.raises(IngestLimitError, match="DPI"):
        rasterize_pdf(source, dpi=dpi)


def test_source_byte_budget_is_checked_before_pdf_parsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "oversized.pdf"
    source.write_bytes(b"1234")
    monkeypatch.setattr(ingest, "MAX_SOURCE_BYTES", 3)
    monkeypatch.setattr(
        pdfium,
        "PdfDocument",
        lambda *args: pytest.fail("oversized input must fail before PDF parsing"),
    )
    with pytest.raises(IngestLimitError, match="byte budget"):
        rasterize_pdf(source, dpi=150)


def test_pdf_page_budget_is_rejected_before_rasterization(tmp_path: Path) -> None:
    source = tmp_path / "too-many-pages.pdf"
    pages = [Image.new("RGB", (8, 8), "white") for _ in range(MAX_PAGES + 1)]
    try:
        pages[0].save(source, "PDF", resolution=72.0, save_all=True, append_images=pages[1:])
    finally:
        for page in pages:
            page.close()

    with pytest.raises(IngestLimitError, match="page budget"):
        rasterize_pdf(source, dpi=72)


def test_pdf_pixel_budget_is_rejected_before_get_pixmap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "huge-page.pdf"
    source.write_bytes(b"synthetic")

    class FakePage:
        def get_size(self) -> tuple[float, float]:
            return 100_000.0, 100_000.0

        def render(self, **kwargs: Any) -> object:
            pytest.fail("pixel budget must fail before rasterization")

        def close(self) -> None:
            pass

    class FakeDocument:
        def __len__(self) -> int:
            return 1

        def __getitem__(self, index: int) -> FakePage:
            assert index == 0
            return FakePage()

        def close(self) -> None:
            pass

    monkeypatch.setattr(pdfium, "PdfDocument", lambda path: FakeDocument())
    with pytest.raises(IngestLimitError, match="pixel budget"):
        rasterize_pdf(source, dpi=300)


def test_pdf_total_pixel_budget_is_checked_before_any_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "one-large-page.pdf"
    source.write_bytes(b"synthetic")
    rendered: list[int] = []

    class FakePage:
        def get_size(self) -> tuple[float, float]:
            return 20.0, 10.0

        def render(self, **kwargs: Any) -> object:
            rendered.append(1)
            raise AssertionError("all page budgets must be checked before rendering")

        def close(self) -> None:
            pass

    class FakeDocument:
        def __len__(self) -> int:
            return 1

        def __getitem__(self, index: int) -> FakePage:
            assert index == 0
            return FakePage()

        def close(self) -> None:
            pass

    monkeypatch.setattr(pdfium, "PdfDocument", lambda path: FakeDocument())
    monkeypatch.setattr(ingest, "MAX_TOTAL_PIXELS", 150)

    with pytest.raises(IngestLimitError, match="total local pixel budget"):
        rasterize_pdf(source, dpi=72)
    assert rendered == []


def test_invalid_pdf_raises_sanitized_document_error(tmp_path: Path) -> None:
    secret = "PERSON-NAME-private-sheet"
    source = tmp_path / f"{secret}.pdf"
    source.write_bytes(b"not a PDF")

    with pytest.raises(IngestDocumentError) as exc_info:
        rasterize_pdf(source, dpi=150)

    message = str(exc_info.value)
    assert message == "PDF could not be opened safely."
    assert secret not in message
    assert str(source) not in message


def test_pdfium_document_and_pages_close_when_render_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "render-failure.pdf"
    source.write_bytes(b"synthetic")
    pages: list[FakePage] = []

    class FakePage:
        def __init__(self) -> None:
            self.closed = False
            pages.append(self)

        def get_size(self) -> tuple[float, float]:
            return 10.0, 10.0

        def render(self, **kwargs: Any) -> object:
            raise RuntimeError("native error containing private/path")

        def close(self) -> None:
            self.closed = True

    class FakeDocument:
        closed = False

        def __len__(self) -> int:
            return 1

        def __getitem__(self, index: int) -> FakePage:
            assert index == 0
            return FakePage()

        def close(self) -> None:
            self.closed = True

    document = FakeDocument()
    monkeypatch.setattr(pdfium, "PdfDocument", lambda path: document)

    with pytest.raises(IngestDocumentError, match="PDF could not be rasterized safely"):
        rasterize_pdf(source, dpi=72)

    assert document.closed is True
    assert len(pages) == 2
    assert all(page.closed for page in pages)


def test_pdfium_document_lifecycles_are_serialized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = [tmp_path / "a.pdf", tmp_path / "b.pdf"]
    for source in sources:
        source.write_bytes(b"synthetic")
    state = {"active": 0, "max_active": 0}
    state_lock = threading.Lock()

    class FakeBitmap:
        width = 1
        height = 1

        def to_pil(self) -> Image.Image:
            return Image.new("RGB", (1, 1), "white")

        def close(self) -> None:
            pass

    class FakePage:
        def get_size(self) -> tuple[float, float]:
            return 1.0, 1.0

        def render(self, **kwargs: Any) -> FakeBitmap:
            time.sleep(0.02)
            return FakeBitmap()

        def close(self) -> None:
            pass

    class FakeDocument:
        def __init__(self, path: Path) -> None:
            with state_lock:
                state["active"] += 1
                state["max_active"] = max(state["max_active"], state["active"])

        def __len__(self) -> int:
            return 1

        def __getitem__(self, index: int) -> FakePage:
            assert index == 0
            return FakePage()

        def close(self) -> None:
            with state_lock:
                state["active"] -= 1

    monkeypatch.setattr(pdfium, "PdfDocument", FakeDocument)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda source: rasterize_pdf(source, dpi=72), sources))

    assert state == {"active": 0, "max_active": 1}
    for images in results:
        assert images[0].getpixel((0, 0)) == (255, 255, 255)
        images[0].close()


def test_image_pixel_budget_is_checked_before_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "large.png"
    Image.new("RGB", (11, 10), "white").save(source)
    monkeypatch.setattr(ingest, "MAX_PIXELS_PER_PAGE", 100)

    with pytest.raises(IngestLimitError, match="pixel budget"):
        load_source_images(source)
