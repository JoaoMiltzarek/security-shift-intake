"""M4.b: tests for the vision client interface and deterministic mock."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.clients.base import DocumentReader, TranscriptionResult, VisionClient
from src.clients.mock import MockVisionClient

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
# MockVisionClient
# ---------------------------------------------------------------------------


def test_mock_satisfies_protocol() -> None:
    assert isinstance(MockVisionClient(), VisionClient)
    assert isinstance(MockVisionClient(), DocumentReader)


def test_mock_returns_configured_result() -> None:
    client = MockVisionClient(text="canned text", confidence=0.42)
    result = client.transcribe("ZmFrZQ==")
    assert result.text == "canned text"
    assert result.confidence == 0.42


def test_mock_is_deterministic() -> None:
    client = MockVisionClient(text="same")
    a = client.transcribe("img1")
    b = client.transcribe("img2")
    assert a == b


def test_mock_records_calls() -> None:
    client = MockVisionClient()
    assert client.call_count == 0
    client.transcribe("base64data")
    assert client.call_count == 1
    assert client.last_image_b64 == "base64data"
