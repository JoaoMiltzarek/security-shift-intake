"""Tests for the document-reader contract and deterministic fake."""

from __future__ import annotations

import pytest
from PIL import Image
from pydantic import ValidationError

from src.clients.base import DocumentReader, TranscriptionResult
from src.clients.mock import FakeDocumentReader
from src.pipeline.ingest import Deadline, PageArtifact

# ---------------------------------------------------------------------------
# TranscriptionResult
# ---------------------------------------------------------------------------


def test_transcription_result_valid() -> None:
    r = TranscriptionResult(text="hello", confidence=0.8)
    assert r.text == "hello"


def test_transcription_result_confidence_bounds() -> None:
    with pytest.raises(ValidationError):
        TranscriptionResult(text="x", confidence=1.5)
    with pytest.raises(ValidationError):
        TranscriptionResult(text="x", confidence=-0.01)


def test_transcription_result_accepts_paddleocr_confidence_source() -> None:
    result = TranscriptionResult(
        text="linha reconhecida",
        confidence=0.83,
        confidence_source="paddleocr",
    )
    assert result.confidence_source == "paddleocr"


# ---------------------------------------------------------------------------
# FakeDocumentReader
# ---------------------------------------------------------------------------


def _page() -> PageArtifact:
    with Image.new("RGB", (2, 2), "white") as image:
        return PageArtifact.from_image(image, page_index=0)


def test_fake_reader_satisfies_protocol() -> None:
    assert isinstance(FakeDocumentReader(), DocumentReader)


def test_fake_reader_returns_configured_result() -> None:
    reader = FakeDocumentReader(text="canned text", confidence=0.42)
    result = reader.read(_page(), Deadline.after(1.0))
    assert result.text == "canned text"
    assert result.confidence == 0.42


def test_fake_reader_is_deterministic() -> None:
    reader = FakeDocumentReader(text="same")
    page = _page()
    a = reader.read(page, Deadline.after(1.0))
    b = reader.read(page, Deadline.after(1.0))
    assert a == b


def test_fake_reader_records_calls() -> None:
    reader = FakeDocumentReader()
    page = _page()
    assert reader.call_count == 0
    reader.read(page, Deadline.after(1.0))
    assert reader.call_count == 1
    assert reader.last_page_sha256 == page.sha256
