"""Font discovery for Tier B rendering.

Looks for handwriting fonts dropped into assets/fonts/. If none are present, falls
back to Pillow's default TrueType font so the pipeline still runs end-to-end in CI
(where no handwriting fonts are installed). Font selection is deterministic given a
passed-in `random.Random`.
"""

from __future__ import annotations

import random
from pathlib import Path

from PIL import ImageFont

# A drawable font — either a scalable TrueType font or Pillow's default font.
# Both support .getlength() and work with ImageDraw.text().
Font = ImageFont.FreeTypeFont | ImageFont.ImageFont

FONTS_DIR = Path("assets/fonts")
_FONT_EXTENSIONS = {".ttf", ".otf"}


def discover_handwriting_fonts(fonts_dir: Path = FONTS_DIR) -> list[Path]:
    """Return sorted handwriting font files in *fonts_dir* (empty if none)."""
    if not fonts_dir.is_dir():
        return []
    return sorted(p for p in fonts_dir.iterdir() if p.suffix.lower() in _FONT_EXTENSIONS)


def has_handwriting_fonts(fonts_dir: Path = FONTS_DIR) -> bool:
    return len(discover_handwriting_fonts(fonts_dir)) > 0


def load_font(
    rng: random.Random,
    size: int,
    fonts_dir: Path = FONTS_DIR,
) -> Font:
    """Load a font at *size*: a random handwriting font if available, else default."""
    fonts = discover_handwriting_fonts(fonts_dir)
    if fonts:
        chosen = rng.choice(fonts)
        return ImageFont.truetype(str(chosen), size=size)
    # Fallback: Pillow's bundled default font (scalable when a size is given).
    return ImageFont.load_default(size=size)
