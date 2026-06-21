"""M4.d: offline tests for the real AnthropicVisionClient.

No network calls: we inject a fake SDK client to verify the request shape, and
check the clear-error path when no API key is configured. The real API path is
validated by `make demo-transcribe` when a key exists (mock-first until then).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.clients.base import TranscriptionResult, VisionClient


class _FakeMessages:
    def __init__(self) -> None:
        self.last_kwargs: dict[str, Any] | None = None

    def parse(self, **kwargs: Any) -> Any:
        self.last_kwargs = kwargs

        class _Resp:
            parsed_output = TranscriptionResult(text="fake transcription", confidence=0.77)

        return _Resp()


class _FakeAnthropic:
    def __init__(self) -> None:
        self.messages = _FakeMessages()


def _client_with_fake() -> tuple[Any, _FakeAnthropic]:
    from src.clients.anthropic_vision import AnthropicVisionClient

    fake = _FakeAnthropic()
    return AnthropicVisionClient(client=fake, model="claude-opus-4-8", max_tokens=512), fake


def test_real_client_satisfies_protocol() -> None:
    client, _ = _client_with_fake()
    assert isinstance(client, VisionClient)


def test_transcribe_builds_image_message_and_returns_result() -> None:
    client, fake = _client_with_fake()
    result = client.transcribe("YmFzZTY0", media_type="image/png")

    assert result == TranscriptionResult(text="fake transcription", confidence=0.77)

    kwargs = fake.messages.last_kwargs
    assert kwargs is not None
    assert kwargs["model"] == "claude-opus-4-8"
    assert kwargs["output_format"] is TranscriptionResult
    content = kwargs["messages"][0]["content"]
    image_block = next(b for b in content if b["type"] == "image")
    assert image_block["source"]["data"] == "YmFzZTY0"
    assert image_block["source"]["media_type"] == "image/png"
    assert any(b["type"] == "text" for b in content)


def test_transcribe_raises_on_unparseable_response() -> None:
    from src.clients.anthropic_vision import AnthropicVisionClient

    class _NoneMessages:
        def parse(self, **kwargs: Any) -> Any:
            class _Resp:
                parsed_output = None

            return _Resp()

    class _NoneClient:
        messages = _NoneMessages()

    client = AnthropicVisionClient(client=_NoneClient())
    with pytest.raises(RuntimeError, match="parseable"):
        client.transcribe("x")


def test_construction_makes_no_network_call() -> None:
    # Constructing with an injected fake client must not touch the network.
    client, _ = _client_with_fake()
    assert client is not None


def test_demo_reports_clear_error_when_client_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Our own error handling (not the SDK's): when the real client fails to set up,
    # the demo prints guidance and exits non-zero. The SDK (0.111) defers the
    # API-key check to request time, so we guard the whole real-call path.
    import src.clients.anthropic_vision as av
    from scripts.demo_transcribe import main

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("no API key configured")

    monkeypatch.setattr(av, "AnthropicVisionClient", _boom)

    rc = main(["--file", str(pdf)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "ANTHROPIC_API_KEY" in captured.err


def test_demo_missing_file_returns_2(capsys: pytest.CaptureFixture[str]) -> None:
    from scripts.demo_transcribe import main

    rc = main(["--file", "does_not_exist.pdf"])
    assert rc == 2
    assert "not found" in capsys.readouterr().err
