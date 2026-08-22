"""Validated evidence geometry shared by OCR, extraction, and review state."""

from __future__ import annotations

import math
import re
from pathlib import PurePosixPath
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator


def _validated_bbox(value: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = value
    if not all(math.isfinite(coordinate) for coordinate in value):
        raise ValueError("bbox coordinates must be finite")
    if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
        raise ValueError("bbox must satisfy 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1")
    return value


BBox = Annotated[tuple[float, float, float, float], AfterValidator(_validated_bbox)]


class PageArtifactRef(BaseModel):
    """Portable identity for one immutable page stored below the evidence root."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    storage_key: str = Field(min_length=1, max_length=512)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    width: int = Field(gt=0)
    height: int = Field(gt=0)

    @field_validator("storage_key")
    @classmethod
    def validate_storage_key(cls, value: str) -> str:
        if "\\" in value or re.search(r"[\x00-\x1f\x7f]", value):
            raise ValueError("storage_key must be a clean POSIX relative path")
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("storage_key must remain below the evidence root")
        if path.as_posix() != value:
            raise ValueError("storage_key must use canonical POSIX syntax")
        return value
