"""Structural contracts for the synthetic v1.1 showcase assets."""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
from types import ModuleType

from PIL import Image, ImageChops, ImageDraw


def _writer() -> ModuleType:
    return importlib.import_module("scripts.build_showcase_gif")


def _gif_contract(path: Path, writer: ModuleType) -> list[Image.Image]:
    with Image.open(path) as gif:
        assert gif.format == "GIF"
        assert gif.is_animated
        assert gif.n_frames == 3
        assert gif.size == writer.OUTPUT_SIZE
        assert gif.info["loop"] == 0
        assert gif.info["comment"] == writer.GIF_COMMENT

        frames: list[Image.Image] = []
        durations: list[int] = []
        for index in range(gif.n_frames):
            gif.seek(index)
            durations.append(int(gif.info["duration"]))
            frames.append(gif.convert("RGB").copy())

    assert tuple(durations) == writer.FRAME_DURATIONS_MS
    pairs = zip(frames, frames[1:], strict=False)
    assert all(ImageChops.difference(a, b).getbbox() for a, b in pairs)
    return frames


def test_writer_builds_three_frame_gif_with_shared_contract(tmp_path: Path) -> None:
    writer = _writer()
    source_paths: list[Path] = []
    for index, color in enumerate(("#f6f3ea", "#dbeafe", "#dcfce7")):
        frame = Image.new("RGB", (1440, 900), color)
        draw = ImageDraw.Draw(frame)
        draw.rectangle((100 + index * 80, 120, 520 + index * 80, 420), fill="#4338ca")
        path = tmp_path / f"frame-{index}.png"
        frame.save(path)
        source_paths.append(path)

    output = tmp_path / "showcase.gif"
    writer.build_showcase_gif(source_paths, output)

    assert output.is_file()
    assert output.stat().st_size < writer.MAX_GIF_BYTES
    _gif_contract(output, writer)


def test_versioned_cockpit_demo_gif_matches_contract() -> None:
    writer = _writer()
    asset = Path("samples/cockpit_demo.gif")
    frames = _gif_contract(asset, writer)
    assert asset.stat().st_size < writer.MAX_GIF_BYTES
    assert len(frames) == 3


def test_versioned_approved_review_screenshot_matches_contract() -> None:
    asset = Path("samples/review_approved.png")

    with Image.open(asset) as screenshot:
        assert screenshot.format == "PNG"
        assert screenshot.size == (1440, 900)
    assert hashlib.sha256(asset.read_bytes()).hexdigest() == (
        "aea6ac9033397d2106f6b391077113ebc185952807940e1ed928df768e321acc"
    )


def test_samples_readme_records_gif_provenance() -> None:
    readme = Path("samples/README.md").read_text(encoding="utf-8")
    required = (
        "b31a545e88a412cf370af0b400582bec7eb7e61d22d4434f859048cb5ac69084",
        "8a47705ac65f835107d4aa11ac2f72254c0ddaaf2fc3b0f456c7ae25868ee4fe",
        "aea6ac9033397d2106f6b391077113ebc185952807940e1ed928df768e321acc",
        "eff49702",
        "FakeDocumentReader",
        "Playwright 1.61.0",
        "Chromium 149.0.7827.55",
        "scripts/browser_smoke.py",
        "scripts.build_showcase_gif",
    )
    assert all(value in readme for value in required)
