"""Evidence boxes are normalized, ordered, finite rectangles."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from src.clients.base import WordBox
from src.schema.extraction import AuditedField
from src.schema.state import ExtractedField


def _word_box(bbox: tuple[float, float, float, float]) -> WordBox:
    return WordBox(text="evidence", bbox=bbox, conf=0.9, line_key="1:1:1")


@pytest.mark.parametrize(
    "bbox",
    [
        (-0.1, 0.1, 0.2, 0.2),
        (0.1, -0.1, 0.2, 0.2),
        (0.1, 0.1, 1.1, 0.2),
        (0.1, 0.1, 0.2, 1.1),
        (0.2, 0.1, 0.2, 0.3),
        (0.3, 0.1, 0.2, 0.3),
        (0.1, 0.3, 0.2, 0.2),
        (math.nan, 0.1, 0.2, 0.3),
        (0.1, 0.1, math.inf, 0.3),
    ],
)
def test_word_box_rejects_invalid_geometry(bbox: tuple[float, float, float, float]) -> None:
    with pytest.raises(ValidationError, match="bbox"):
        _word_box(bbox)


def test_all_persisted_evidence_models_share_bbox_validation() -> None:
    invalid = (0.8, 0.1, 0.2, 0.3)

    with pytest.raises(ValidationError):
        AuditedField(bbox=invalid)
    with pytest.raises(ValidationError):
        ExtractedField(name="unit", value="1", confidence=0.9, bbox=invalid)


def test_boundary_aligned_bbox_is_valid() -> None:
    bbox = (0.0, 0.0, 1.0, 1.0)
    assert _word_box(bbox).bbox == bbox
