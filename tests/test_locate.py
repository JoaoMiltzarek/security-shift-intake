"""PR2 — evidence locator: 3-level matching + normalized (accent/case/punct) match.

These pin the honesty contract: a value gets `exact`/`token_window` only when the OCR
words actually back it, `none` (bbox=None) otherwise, and OCR noise (accents, case,
punctuation) never blocks a real match.
"""

from __future__ import annotations

import pytest

from src.clients.base import WordBox
from src.pipeline.locate import attach_evidence, locate_value
from src.schema.state import ExtractedField


def _wb(text: str, *, x0: float, line_key: str = "0:0:0", page: int = 0) -> WordBox:
    return WordBox(
        text=text, bbox=(x0, 0.0, x0 + 0.1, 0.1), conf=0.9, line_key=line_key, page=page
    )


def test_exact_contiguous_run() -> None:
    words = [_wb("Torre", x0=0.1), _wb("I", x0=0.2)]
    match = locate_value("Torre I", words)
    assert match.method == "exact"
    assert match.score == 1.0
    assert match.bbox == pytest.approx((0.1, 0.0, 0.3, 0.1))  # union of both


def test_token_window_partial_match_same_line() -> None:
    # "Ana" and "Souza" are on the line but not adjacent, and "Lima" is absent.
    words = [
        _wb("Vigilante", x0=0.0, line_key="1:1:1"),
        _wb("Ana", x0=0.2, line_key="1:1:1"),
        _wb("X", x0=0.4, line_key="1:1:1"),
        _wb("Souza", x0=0.6, line_key="1:1:1"),
    ]
    match = locate_value("Ana Souza Lima", words)
    assert match.method == "token_window"
    assert match.score == 2 / 3  # 2 of 3 value tokens matched
    assert match.bbox is not None


def test_absent_value_is_none() -> None:
    words = [_wb("Portaria", x0=0.0)]
    match = locate_value("Inexistente", words)
    assert match.method == "none"
    assert match.bbox is None
    assert match.score == 0.0


def test_normalized_match_ignores_accent_and_punctuation() -> None:
    words = [_wb("Operação,", x0=0.0)]
    match = locate_value("operacao", words)
    assert match.method == "exact"  # accent + trailing comma normalized away


def test_token_window_respects_line_key() -> None:
    # Value tokens split across two OCR lines must not merge into one window. A filler
    # word between them also prevents an exact contiguous run.
    words = [
        _wb("Ana", x0=0.0, line_key="1:1:1"),
        _wb("filler", x0=0.3, line_key="1:1:1"),
        _wb("Souza", x0=0.0, line_key="2:1:1"),
    ]
    match = locate_value("Ana Souza", words)
    # No single line holds both → best window is one token, not a merged region.
    assert match.method == "token_window"
    assert match.score == 0.5


def test_attach_evidence_noop_without_geometry() -> None:
    fields = [ExtractedField(name="x", value="Torre", confidence=0.9)]
    out = attach_evidence(fields, None)
    assert out[0].bbox is None
    assert out[0].evidence_method is None  # locator never ran


def test_attach_evidence_skips_human_edited_fields() -> None:
    words = [_wb("Torre", x0=0.1)]
    fields = [ExtractedField(name="x", value="Torre", confidence=1.0, source="human")]
    out = attach_evidence(fields, words)
    assert out[0].bbox is None  # human value keeps no OCR bbox (invariant 4)
    assert out[0].evidence_method is None
