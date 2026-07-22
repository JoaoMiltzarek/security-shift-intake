"""Phase 2 reader: LocalVLMVisionClient + the vision factory.

All offline at $0: a fake Transport returns canned OpenAI-compatible JSON, so no
server and no network are needed (spec §8.4). Mirrors test_local_ocr.py's "real or
clear error" honesty — here the error path is a malformed/empty response.
"""

from __future__ import annotations

import math
from typing import Any

import httpx
import pytest
from PIL import Image

from evals.readers.factory import get_evaluation_reader
from evals.readers.local_vlm import (
    LocalVLMVisionClient,
    _build_payload,
    _ChatResponse,
    _confidence_from_logprobs,
    _parse_text,
)
from src.clients.base import DocumentReader, TranscriptionResult, VisionClient
from src.pipeline.ingest import Deadline, PageArtifact


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
    assert isinstance(client, DocumentReader)


def _page() -> PageArtifact:
    with Image.new("RGB", (10, 10), "white") as image:
        return PageArtifact.from_image(image, page_index=0)


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


def test_read_encodes_page_bytes_inside_the_adapter() -> None:
    transport = FakeTransport(_response("x"))
    client = LocalVLMVisionClient(transport=transport)
    page = _page()

    client.read(page, Deadline.after(5.0))

    assert transport.last_payload is not None
    content = transport.last_payload["messages"][0]["content"]
    data_url = next(part["image_url"]["url"] for part in content if part["type"] == "image_url")
    assert data_url.startswith("data:image/png;base64,")


# --- confidence is honest: real from logprobs, conservative default otherwise ---


def test_confidence_from_logprobs() -> None:
    # probs 0.9 and 0.8 -> mean 0.85
    transport = FakeTransport(_response("ok", logprobs=[math.log(0.9), math.log(0.8)]))
    client = LocalVLMVisionClient(transport=transport)
    result = client.transcribe("ZmFrZQ==")
    assert result.confidence == pytest.approx(0.85)
    assert result.confidence_source == "logprobs"


def test_confidence_falls_back_to_default_without_logprobs() -> None:
    transport = FakeTransport(_response("ok"))  # no logprobs
    client = LocalVLMVisionClient(transport=transport, default_confidence=0.33)
    result = client.transcribe("ZmFrZQ==")
    assert result.confidence == 0.33
    assert result.confidence_source == "placeholder"


def test_confidence_helper_clamps_to_unit_interval() -> None:
    # A positive logprob (possible with some servers) must not exceed 1.0.
    response = _ChatResponse.model_validate(_response("ok", logprobs=[0.5]))
    assert _confidence_from_logprobs(response, default=0.5) == (1.0, "logprobs")


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


# --- evaluation-only reader factory ---


def test_product_factory_default_is_local_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.clients.factory import get_vision_client
    from src.clients.local_ocr import LocalOCRVisionClient

    monkeypatch.setenv("INTAKE_VISION", "local_vlm")
    assert isinstance(get_vision_client(), LocalOCRVisionClient)


def test_evaluation_factory_selects_local_vlm() -> None:
    assert isinstance(get_evaluation_reader("local_vlm"), LocalVLMVisionClient)


def test_evaluation_factory_selects_mock() -> None:
    from src.clients.mock import MockVisionClient

    assert isinstance(get_evaluation_reader("mock"), MockVisionClient)


def test_evaluation_factory_unknown_name_raises() -> None:
    with pytest.raises(ValueError, match="Unknown evaluation reader"):
        get_evaluation_reader("does-not-exist")


def test_default_transport_never_inherits_proxy_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        captured.update(url=url, **kwargs)
        request = httpx.Request("POST", url)
        return httpx.Response(200, request=request, json=_response("texto local"))

    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9999")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setattr(httpx, "post", fake_post)

    client = LocalVLMVisionClient(base_url="http://127.0.0.1:11434/v1")
    assert client.transcribe("ZmFrZQ==").text == "texto local"
    assert captured["trust_env"] is False


def test_page_deadline_clamps_local_vlm_http_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        captured.update(url=url, **kwargs)
        request = httpx.Request("POST", url)
        return httpx.Response(200, request=request, json=_response("texto local"))

    monkeypatch.setattr(httpx, "post", fake_post)
    deadline = Deadline.after(1.5, clock=lambda: 10.0)

    LocalVLMVisionClient(base_url="http://127.0.0.1:11434/v1").read(_page(), deadline)

    assert captured["timeout"] == 1.5


# --- retry sem logprobs (medido: Ollama 0.31.1 -> 500 com logprobs+visão) ------


class _LogprobRejectingTransport:
    """Simula o Ollama: HTTP 500 se o payload pede logprobs; sucesso sem eles."""

    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response
        self.payloads: list[dict[str, Any]] = []

    def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.payloads.append(payload)
        if payload.get("logprobs"):
            error = httpx.HTTPStatusError(
                "500", request=httpx.Request("POST", "http://x"), response=httpx.Response(500)
            )
            raise RuntimeError("server rejected logprobs") from error
        return self._response


def test_transcribe_retries_without_logprobs_on_http_status_error() -> None:
    transport = _LogprobRejectingTransport(_response("Data: 15/01"))
    client = LocalVLMVisionClient(transport=transport, default_confidence=0.5)
    result = client.transcribe("ZmFrZQ==")
    assert result.text == "Data: 15/01"
    assert result.confidence_source == "placeholder"  # sem logprobs -> honesto
    assert [bool(p.get("logprobs")) for p in transport.payloads] == [True, False]


def test_transcribe_does_not_retry_on_connection_error() -> None:
    def _refuses(payload: dict[str, Any]) -> dict[str, Any]:
        error = httpx.ConnectError("refused")
        raise RuntimeError("no server") from error

    client = LocalVLMVisionClient(transport=_refuses)
    with pytest.raises(RuntimeError, match="no server"):
        client.transcribe("ZmFrZQ==")


def test_transcribe_does_not_retry_unrelated_http_status() -> None:
    calls = 0

    def unauthorized(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        response = httpx.Response(401, request=httpx.Request("POST", "http://localhost"))
        error = httpx.HTTPStatusError("unauthorized", request=response.request, response=response)
        raise RuntimeError("local VLM request failed") from error

    with pytest.raises(RuntimeError, match="request failed"):
        LocalVLMVisionClient(transport=unauthorized).transcribe("ZmFrZQ==")
    assert calls == 1


def test_malformed_vlm_response_never_echoes_response_content() -> None:
    sensitive_marker = "SYNTHETIC-SENSITIVE-MARKER"
    malformed = {"choices": [{"message": {"content": {"value": sensitive_marker}}}]}
    client = LocalVLMVisionClient(transport=FakeTransport(malformed))

    with pytest.raises(RuntimeError, match="invalid response shape") as exc_info:
        client.transcribe("ZmFrZQ==")
    assert sensitive_marker not in str(exc_info.value)


def test_invalid_vlm_json_never_echoes_response_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensitive_marker = "SYNTHETIC-SENSITIVE-MARKER"

    def invalid_json(url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            content=("{" + sensitive_marker).encode(),
        )

    monkeypatch.setattr(httpx, "post", invalid_json)
    client = LocalVLMVisionClient(base_url="http://127.0.0.1:11434/v1")

    with pytest.raises(RuntimeError, match="invalid JSON") as exc_info:
        client.transcribe("ZmFrZQ==")
    assert sensitive_marker not in str(exc_info.value)
