"""M6.a: classify stage (mock) + offline test of the real client's classify."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.clients.base import ClassificationResult
from src.clients.mock import MockLLMClient
from src.pipeline.classify import classify
from src.schema.loader import load_config
from src.schema.state import PipelineState

CONFIG = load_config(Path("configs/htmicron_security.yaml"))


def test_classify_populates_state() -> None:
    client = MockLLMClient(
        classification=ClassificationResult(
            incident_type="theft", urgency="high", sector="tech_security", confidence=0.88
        )
    )
    state = PipelineState(source_pdf=Path("x.pdf"), transcription="...furto...")
    result = classify(state, client, CONFIG)

    assert result.classification is not None
    assert result.classification.incident_type == "theft"
    assert result.classification.urgency == "high"
    assert result.classification.sector == "tech_security"
    assert result.classification.confidence == 0.88
    assert client.classify_count == 1


def test_classify_passes_taxonomy_labels() -> None:
    # The mock ignores the labels but the stage must pass the config taxonomy.
    captured: dict[str, Any] = {}

    class _SpyClient(MockLLMClient):
        def classify(self, transcription, types, urgencies, sectors):  # type: ignore[no-untyped-def]
            captured["types"] = types
            captured["urgencies"] = urgencies
            captured["sectors"] = sectors
            return super().classify(transcription, types, urgencies, sectors)

    state = PipelineState(source_pdf=Path("x.pdf"), transcription="...")
    classify(state, _SpyClient(), CONFIG)
    assert "critical" in captured["urgencies"]
    assert "theft" in captured["types"]
    assert "facilities" in captured["sectors"]


def test_classify_does_not_mutate_input() -> None:
    state = PipelineState(source_pdf=Path("x.pdf"), transcription="...")
    classify(state, MockLLMClient(), CONFIG)
    assert state.classification is None


# --- Real client classify, offline (fake SDK) ---


class _FakeMessages:
    def parse(self, **kwargs: Any) -> Any:
        self.last_kwargs = kwargs

        class _Resp:
            parsed_output = ClassificationResult(
                incident_type="safety", urgency="critical", sector="facilities", confidence=0.7
            )

        return _Resp()


class _FakeAnthropic:
    def __init__(self) -> None:
        self.messages = _FakeMessages()


def test_real_client_classify_offline() -> None:
    from src.clients.anthropic_llm import AnthropicLLMClient

    fake = _FakeAnthropic()
    client = AnthropicLLMClient(client=fake, model="claude-opus-4-8")
    result = client.classify("fire alarm", ["safety"], ["critical"], ["facilities"])

    assert result.incident_type == "safety"
    assert fake.messages.last_kwargs["output_format"] is ClassificationResult
    assert "critical" in fake.messages.last_kwargs["messages"][0]["content"]
