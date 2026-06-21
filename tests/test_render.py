"""M3.b: tests for the form renderer (dimensions, determinism, content drawn)."""

from __future__ import annotations

import random

from PIL import Image

from data.generators.messiness import inject_messiness
from data.generators.records import generate_record
from data.generators.render import RENDER_HEIGHT, RENDER_WIDTH, render_form


def _surface(seed: int):
    rng = random.Random(seed)
    rec = generate_record(rng, f"rec-{seed}")
    return inject_messiness(rng, rec)


def test_render_returns_expected_dimensions() -> None:
    img = render_form(random.Random(0), _surface(1))
    assert isinstance(img, Image.Image)
    assert img.size == (RENDER_WIDTH, RENDER_HEIGHT)
    assert img.mode == "RGB"


def test_render_is_deterministic() -> None:
    s = _surface(3)
    a = render_form(random.Random(7), s)
    b = render_form(random.Random(7), s)
    assert a.tobytes() == b.tobytes()


def test_render_draws_ink_not_blank() -> None:
    img = render_form(random.Random(0), _surface(2)).convert("L")
    extrema = img.getextrema()  # (min, max)
    # There must be dark pixels (text) and light pixels (paper).
    assert extrema[0] < 80
    assert extrema[1] > 200


def test_different_records_render_differently() -> None:
    a = render_form(random.Random(0), _surface(10))
    b = render_form(random.Random(0), _surface(11))
    assert a.tobytes() != b.tobytes()


def test_custom_dimensions_respected() -> None:
    img = render_form(random.Random(0), _surface(1), width=600, height=800)
    assert img.size == (600, 800)
