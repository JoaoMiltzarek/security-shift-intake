"""Canvas primitives shared by the canonical synthetic occurrence form."""

from __future__ import annotations

import random

from PIL import ImageDraw

from data.generators.fonts import Font

RENDER_WIDTH = 1000
RENDER_HEIGHT = 1414

_INK = (15, 20, 60)


def draw_handwritten(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: Font,
    rng: random.Random,
) -> None:
    """Draw text character by character with deterministic baseline jitter."""
    x, y = xy
    for character in text:
        vertical_jitter = rng.randint(-3, 3)
        draw.text((x, y + vertical_jitter), character, font=font, fill=_INK)
        x += int(font.getlength(character) + rng.randint(-1, 1))


def wrap_handwritten(text: str, font: Font, max_width: int) -> list[str]:
    """Greedily wrap a handwritten value within the available width."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if font.getlength(candidate) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines
