#!/usr/bin/env python3
"""Assemble three synthetic cockpit screenshots into the versioned showcase GIF."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

OUTPUT_SIZE = (1200, 750)
FRAME_DURATIONS_MS = (1400, 2400, 2400)
MAX_GIF_BYTES = 5 * 1024 * 1024
GIF_COMMENT = (
    b"synthetic-only; source=samples/sample_tc-000000.png; reader=tesseract; "
    b"generated-by=scripts/build_showcase_gif.py"
)


def _load_frame(path: Path) -> Image.Image:
    with Image.open(path) as source:
        return source.convert("RGB").resize(OUTPUT_SIZE, Image.Resampling.LANCZOS)


def _shared_palette(frames: list[Image.Image]) -> Image.Image:
    """Build one palette from every frame so GIF playback does not color-flicker."""
    width, height = OUTPUT_SIZE
    atlas = Image.new("RGB", (width, height * len(frames)))
    for index, frame in enumerate(frames):
        atlas.paste(frame, (0, index * height))
    return atlas.quantize(colors=256, method=Image.Quantize.MEDIANCUT)


def build_showcase_gif(frame_paths: list[Path], output: Path) -> None:
    """Write the fixed three-frame GIF contract atomically to *output*."""
    if len(frame_paths) != len(FRAME_DURATIONS_MS):
        raise ValueError(f"expected exactly {len(FRAME_DURATIONS_MS)} frames")
    missing = [path for path in frame_paths if not path.is_file()]
    if missing:
        raise ValueError(f"missing frame(s): {', '.join(str(path) for path in missing)}")

    frames = [_load_frame(path) for path in frame_paths]
    palette = _shared_palette(frames)
    paletted = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    try:
        paletted[0].save(
            temporary,
            format="GIF",
            save_all=True,
            append_images=paletted[1:],
            duration=list(FRAME_DURATIONS_MS),
            loop=0,
            disposal=2,
            optimize=False,
            comment=GIF_COMMENT,
        )
        if temporary.stat().st_size >= MAX_GIF_BYTES:
            raise ValueError(f"GIF is {temporary.stat().st_size} bytes; limit is {MAX_GIF_BYTES}")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build the synthetic cockpit showcase GIF.")
    parser.add_argument("frames", nargs=3, type=Path, help="initial/highlight/edit PNGs")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("samples/cockpit_demo.gif"),
    )
    args = parser.parse_args(argv)
    try:
        build_showcase_gif(args.frames, args.output)
    except (OSError, ValueError) as exc:
        print(f"Could not build showcase GIF: {exc}", file=sys.stderr)
        return 2
    print(f"Built synthetic showcase GIF: {args.output} ({args.output.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
