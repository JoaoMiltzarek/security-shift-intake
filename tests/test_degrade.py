"""M3.c: tests for scan degradation (shape preserved, deterministic, legible)."""

from __future__ import annotations

import random

import numpy as np
from PIL import Image

from data.generators.degrade import degrade_scan


def _sample_image(size: tuple[int, int] = (400, 560)) -> Image.Image:
    # White paper with a dark rectangle standing in for text.
    img = Image.new("RGB", size, "white")
    arr = np.asarray(img).copy()
    arr[100:140, 50:350] = (10, 10, 40)
    return Image.fromarray(arr, mode="RGB")


def test_output_preserves_size_and_mode() -> None:
    img = _sample_image()
    out = degrade_scan(random.Random(0), img)
    assert out.size == img.size
    assert out.mode == img.mode


def test_degradation_is_deterministic() -> None:
    img = _sample_image()
    a = degrade_scan(random.Random(42), img)
    b = degrade_scan(random.Random(42), img)
    assert a.tobytes() == b.tobytes()


def test_output_differs_from_input() -> None:
    img = _sample_image()
    out = degrade_scan(random.Random(1), img)
    assert out.tobytes() != img.tobytes()


def test_different_seeds_differ() -> None:
    img = _sample_image()
    a = degrade_scan(random.Random(1), img)
    b = degrade_scan(random.Random(2), img)
    assert a.tobytes() != b.tobytes()


def test_still_legible_mostly_light() -> None:
    # The page should remain mostly light (paper), i.e. not destroyed by noise.
    img = _sample_image()
    out = degrade_scan(random.Random(3), img).convert("L")
    mean = float(np.asarray(out).mean())
    assert mean > 150


def test_works_on_grayscale_input() -> None:
    img = _sample_image().convert("L")
    out = degrade_scan(random.Random(0), img)
    assert out.mode == "L"
    assert out.size == img.size
