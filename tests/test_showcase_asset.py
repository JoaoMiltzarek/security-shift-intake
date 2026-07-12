"""F8.2 (SSI-1011): contrato estrutural do GIF sintético do cockpit."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType

import pytest
from PIL import Image, ImageChops, ImageDraw

_ASSET_PENDING = pytest.mark.xfail(
    strict=True,
    reason="SSI-1011: samples/cockpit_demo.gif ainda não foi capturado",
)


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


@_ASSET_PENDING
def test_versioned_cockpit_demo_gif_matches_contract() -> None:
    writer = _writer()
    asset = Path("samples/cockpit_demo.gif")
    frames = _gif_contract(asset, writer)
    assert asset.stat().st_size < writer.MAX_GIF_BYTES
    assert len(frames) == 3
