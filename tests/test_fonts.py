"""M3.a: tests for font discovery and loading (fallback path works in CI)."""

from __future__ import annotations

import random
from pathlib import Path

from PIL import ImageFont

from data.generators import fonts


def _rng(seed: int = 0) -> random.Random:
    return random.Random(seed)


def test_discover_returns_empty_for_missing_dir(tmp_path: Path) -> None:
    assert fonts.discover_handwriting_fonts(tmp_path / "nope") == []


def test_discover_finds_only_font_files(tmp_path: Path) -> None:
    (tmp_path / "a.ttf").write_bytes(b"not-a-real-font")
    (tmp_path / "b.otf").write_bytes(b"not-a-real-font")
    (tmp_path / "c.txt").write_text("ignore me", encoding="utf-8")
    found = fonts.discover_handwriting_fonts(tmp_path)
    assert [p.name for p in found] == ["a.ttf", "b.otf"]


def test_has_handwriting_fonts_false_when_empty(tmp_path: Path) -> None:
    assert fonts.has_handwriting_fonts(tmp_path) is False


def test_load_font_fallback_returns_usable_font(tmp_path: Path) -> None:
    # Empty dir → fallback to Pillow default.
    font = fonts.load_font(_rng(), size=24, fonts_dir=tmp_path / "empty")
    assert isinstance(font, ImageFont.FreeTypeFont)
    # The font can measure text (proves it's actually usable for drawing).
    length = font.getlength("ABC")
    assert length > 0


def test_load_font_is_deterministic(tmp_path: Path) -> None:
    f1 = fonts.load_font(_rng(5), size=20, fonts_dir=tmp_path)
    f2 = fonts.load_font(_rng(5), size=20, fonts_dir=tmp_path)
    assert f1.getlength("hello") == f2.getlength("hello")
