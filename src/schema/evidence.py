"""Validated evidence geometry shared by OCR, extraction, and review state."""

from __future__ import annotations

import math
from typing import Annotated

from pydantic import AfterValidator


def _validated_bbox(value: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = value
    if not all(math.isfinite(coordinate) for coordinate in value):
        raise ValueError("bbox coordinates must be finite")
    if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
        raise ValueError("bbox must satisfy 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1")
    return value


BBox = Annotated[tuple[float, float, float, float], AfterValidator(_validated_bbox)]
