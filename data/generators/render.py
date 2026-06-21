"""Tier B step 1: render a SurfaceText onto a form-like image.

Layout mimics the real form: printed field labels (typed default font) plus
handwritten values (a handwriting font if available, else the default font) drawn
with small per-glyph jitter to avoid one uniform "hand". Everything is seeded.

The clean ground truth is never touched here — we only render the (already messy)
surface strings.
"""

from __future__ import annotations

import random

from PIL import Image, ImageDraw, ImageFont

from data.generators.fonts import Font, load_font
from data.generators.messiness import SurfaceText

# Canvas (portrait, ~A4 aspect). Kept modest for fast tests; DPI handled at export.
RENDER_WIDTH = 1000
RENDER_HEIGHT = 1414

_MARGIN = 70
_LABEL_SIZE = 26
_VALUE_SIZE = 30
_TITLE_SIZE = 34
_LINE_GAP = 58
_LABEL_COL = 240  # x where handwritten values start
_INK = (15, 20, 60)  # dark blue-black ink
_PRINT = (0, 0, 0)  # printed labels in black

_TITLE = "RELATORIO DE TURNO - SEGURANCA"

# (label, attribute on SurfaceText) in form order.
_ROWS: list[tuple[str, str]] = [
    ("Data:", "shift_date_text"),
    ("Vigilante:", "guard_name_text"),
    ("Posto:", "post_text"),
    ("Turno:", "shift_period_text"),
    ("Ocorrencia:", "incident_occurred_text"),
]


def _draw_handwritten(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: Font,
    rng: random.Random,
) -> None:
    """Draw text char-by-char with small baseline/spacing jitter (handwriting feel)."""
    x, y = xy
    for ch in text:
        dy = rng.randint(-3, 3)
        draw.text((x, y + dy), ch, font=font, fill=_INK)
        advance = font.getlength(ch)
        x += int(advance + rng.randint(-1, 1))


def _wrap(text: str, font: Font, max_width: int) -> list[str]:
    """Greedy word-wrap so a line fits within *max_width* pixels."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if font.getlength(trial) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def render_form(
    rng: random.Random,
    surface: SurfaceText,
    width: int = RENDER_WIDTH,
    height: int = RENDER_HEIGHT,
) -> Image.Image:
    """Render *surface* to an RGB image laid out like the shift report form."""
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)

    label_font = ImageFont.load_default(size=_LABEL_SIZE)
    title_font = ImageFont.load_default(size=_TITLE_SIZE)
    value_font = load_font(rng, size=_VALUE_SIZE)

    # Title (printed) + underline.
    draw.text((_MARGIN, _MARGIN), _TITLE, font=title_font, fill=_PRINT)
    y = _MARGIN + _TITLE_SIZE + 24
    draw.line([(_MARGIN, y), (width - _MARGIN, y)], fill=_PRINT, width=2)
    y += 30

    # Single-line labeled rows.
    for label, attr in _ROWS:
        draw.text((_MARGIN, y), label, font=label_font, fill=_PRINT)
        value = getattr(surface, attr)
        _draw_handwritten(draw, (_LABEL_COL, y), str(value), value_font, rng)
        y += _LINE_GAP

    # Free-text description block.
    draw.text((_MARGIN, y), "Descricao:", font=label_font, fill=_PRINT)
    y += _LINE_GAP
    desc = surface.incident_description_text
    if desc:
        for line in _wrap(desc, value_font, width - 2 * _MARGIN):
            _draw_handwritten(draw, (_MARGIN, y), line, value_font, rng)
            y += _LINE_GAP

    return canvas
