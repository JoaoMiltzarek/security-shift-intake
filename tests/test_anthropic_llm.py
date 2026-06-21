"""M5.c: offline tests for the real AnthropicLLMClient (no network calls)."""

from __future__ import annotations

from typing import Any

import pytest

from src.clients.base import ExtractedFieldRaw, ExtractionResponse, LLMClient


class _FakeMessages:
    def __init__(self) -> None:
        self.last_kwargs: dict[str, Any] | None = None

    def parse(self, **kwargs: Any) -> Any:
        self.last_kwargs = kwargs

        class _Resp:
            parsed_output = ExtractionResponse(
                fields=[ExtractedFieldRaw(name="guard_name", value="A. Souza", confidence=0.9)]
            )

        return _Resp()


class _FakeAnthropic:
    def __init__(self) -> None:
        self.messages = _FakeMessages()


def _client() -> tuple[Any, _FakeAnthropic]:
    from src.clients.anthropic_llm import AnthropicLLMClient

    fake = _FakeAnthropic()
    return AnthropicLLMClient(client=fake, model="claude-opus-4-8", max_tokens=512), fake


def test_real_llm_satisfies_protocol() -> None:
    client, _ = _client()
    assert isinstance(client, LLMClient)


def test_extract_builds_prompt_and_returns_fields() -> None:
    client, fake = _client()
    fields = client.extract_fields("Vigilante: A. Souza", ["guard_name", "post"])

    assert fields[0].name == "guard_name"
    kwargs = fake.messages.last_kwargs
    assert kwargs is not None
    assert kwargs["model"] == "claude-opus-4-8"
    assert kwargs["output_format"] is ExtractionResponse
    prompt = kwargs["messages"][0]["content"]
    assert "guard_name" in prompt and "post" in prompt
    assert "Vigilante: A. Souza" in prompt


def test_extract_raises_on_unparseable_response() -> None:
    from src.clients.anthropic_llm import AnthropicLLMClient

    class _NoneMessages:
        def parse(self, **kwargs: Any) -> Any:
            class _Resp:
                parsed_output = None

            return _Resp()

    class _NoneClient:
        messages = _NoneMessages()

    client = AnthropicLLMClient(client=_NoneClient())
    with pytest.raises(RuntimeError, match="parseable"):
        client.extract_fields("x", ["guard_name"])
