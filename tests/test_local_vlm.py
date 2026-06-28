"""Phase 2 reader: LocalVLMVisionClient + the vision factory.

All offline at $0: a fake Transport returns canned OpenAI-compatible JSON, so no
server and no network are needed (spec §8.4). Mirrors test_local_ocr.py's "real or
clear error" honesty — here the error path is a malformed/empty response.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from src.clients.base import TranscriptionResult, VisionClient
from src.clients.factory import get_vision_client
from src.clients.local_vlm import (
    LocalVLMVisionClient,
    _build_payload,
    _ChatResponse,
    _confidence_from_logprobs,
    _parse_text,
)


def _response(text: str | None, logprobs: list[float] | None = None) -> dict[str, Any]:
    """Build a canned OpenAI chat-completions response dict."""
    choice: dict[str, Any] = {"message": {"content": text}}
    if logprobs is not None:
        choice["logprobs"] = {"content": [{"logprob": lp} for lp in logprobs]}
    return {"choices": [choice]}


class FakeTransport:
    """Records the last payload and returns a fixed response (no network)."""

    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response
        self.last_payload: dict[str, Any] | None = None
        self.calls = 0

    def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        self.last_payload = payload
        return self._response


# --- protocol conformance ---


def test_client_satisfies_protocol() -> None:
    client = LocalVLMVisionClient(transport=FakeTransport(_response("hi")))
    assert isinstance(client, VisionClient)


# --- transcribe end to end (mocked transport) ---


def test_transcribe_returns_model_text() -> None:
    transport = FakeTransport(_response("Data: 15/01/2026\nVigilante: A. Souza"))
    client = LocalVLMVisionClient(transport=transport)
    result = client.transcribe("ZmFrZQ==")
    assert isinstance(result, TranscriptionResult)
    assert result.text == "Data: 15/01/2026\nVigilante: A. Souza"
    assert transport.calls == 1


def test_transcribe_builds_data_url_with_media_type() -> None:
    transport = FakeTransport(_response("x"))
    client = LocalVLMVisionClient(transport=transport)
    client.transcribe("QUJD", media_type="image/jpeg")
    assert transport.last_payload is not None
    content = transport.last_payload["messages"][0]["content"]
    image_parts = [p for p in content if p["type"] == "image_url"]
    assert image_parts[0]["image_url"]["url"] == "data:image/jpeg;base64,QUJD"


# --- confidence is honest: real from logprobs, conservative default otherwise ---


def test_confidence_from_logprobs() -> None:
    # probs 0.9 and 0.8 -> mean 0.85
    transport = FakeTransport(_response("ok", logprobs=[math.log(0.9), math.log(0.8)]))
    client = LocalVLMVisionClient(transport=transport)
    result = client.transcribe("ZmFrZQ==")
    assert result.confidence == pytest.approx(0.85)


def test_confidence_falls_back_to_default_without_logprobs() -> None:
    transport = FakeTransport(_response("ok"))  # no logprobs
    client = LocalVLMVisionClient(transport=transport, default_confidence=0.33)
    result = client.transcribe("ZmFrZQ==")
    assert result.confidence == 0.33


def test_confidence_helper_clamps_to_unit_interval() -> None:
    # A positive logprob (possible with some servers) must not exceed 1.0.
    response = _ChatResponse.model_validate(_response("ok", logprobs=[0.5]))
    assert _confidence_from_logprobs(response, default=0.5) == 1.0


# --- error path: malformed / empty response raises a clear error (no fabrication) ---


def test_empty_choices_raises_clear_error() -> None:
    client = LocalVLMVisionClient(transport=FakeTransport({"choices": []}))
    with pytest.raises(RuntimeError, match="no choices"):
        client.transcribe("ZmFrZQ==")


def test_null_content_raises_clear_error() -> None:
    client = LocalVLMVisionClient(transport=FakeTransport(_response(None)))
    with pytest.raises(RuntimeError, match="no text content"):
        client.transcribe("ZmFrZQ==")


# --- pure helpers (tested directly, like _reconstruct in test_local_ocr) ---


def test_build_payload_shape() -> None:
    payload = _build_payload("ABC", "image/png", "qwen2.5vl:3b")
    assert payload["model"] == "qwen2.5vl:3b"
    assert payload["temperature"] == 0.0
    content = payload["messages"][0]["content"]
    assert any(p["type"] == "text" for p in content)
    assert any(p["type"] == "image_url" for p in content)


def test_parse_text_requires_content() -> None:
    with pytest.raises(RuntimeError):
        _parse_text(_ChatResponse.model_validate({"choices": []}))


# --- factory: selection by env var ---


def test_factory_default_is_local_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.clients.local_ocr import LocalOCRVisionClient

    monkeypatch.delenv("INTAKE_VISION", raising=False)
    assert isinstance(get_vision_client(), LocalOCRVisionClient)


def test_factory_selects_local_vlm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTAKE_VISION", "local_vlm")
    assert isinstance(get_vision_client(), LocalVLMVisionClient)


def test_factory_explicit_arg_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTAKE_VISION", "local_vlm")
    from src.clients.mock import MockVisionClient

    assert isinstance(get_vision_client("mock"), MockVisionClient)


def test_factory_unknown_name_raises() -> None:
    with pytest.raises(ValueError, match="Unknown INTAKE_VISION"):
        get_vision_client("does-not-exist")
