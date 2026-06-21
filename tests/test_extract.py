"""M5.a: extract stage with the mock LLM client (deterministic, $0)."""

from __future__ import annotations

from pathlib import Path

from src.clients.base import ExtractedFieldRaw, LLMClient
from src.clients.mock import MockLLMClient
from src.pipeline.extract import extract
from src.schema.loader import load_config
from src.schema.state import PipelineState

CONFIG = load_config(Path("configs/htmicron_security.yaml"))


def test_mock_satisfies_llm_protocol() -> None:
    assert isinstance(MockLLMClient(), LLMClient)


def test_extract_populates_all_configured_fields() -> None:
    client = MockLLMClient(
        [
            ExtractedFieldRaw(name="guard_name", value="A. Souza", confidence=0.95),
            ExtractedFieldRaw(name="shift_period", value="day", confidence=0.9),
        ]
    )
    state = PipelineState(source_pdf=Path("x.pdf"), transcription="...")
    result = extract(state, client, CONFIG)

    names = {f.name for f in result.extracted_fields}
    assert names == {f.name for f in CONFIG.fields}  # one entry per configured field


def test_extract_carries_value_and_confidence() -> None:
    client = MockLLMClient(
        [ExtractedFieldRaw(name="guard_name", value="A. Souza", confidence=0.95)]
    )
    state = PipelineState(source_pdf=Path("x.pdf"), transcription="...")
    result = extract(state, client, CONFIG)

    guard = next(f for f in result.extracted_fields if f.name == "guard_name")
    assert guard.value == "A. Souza"
    assert guard.confidence == 0.95
    assert guard.must_review is False  # flagging is the critic's job


def test_unprovided_fields_come_back_null() -> None:
    client = MockLLMClient([])  # nothing configured
    state = PipelineState(source_pdf=Path("x.pdf"), transcription="...")
    result = extract(state, client, CONFIG)
    assert all(f.value is None for f in result.extracted_fields)


def test_extract_does_not_mutate_input() -> None:
    client = MockLLMClient([])
    state = PipelineState(source_pdf=Path("x.pdf"), transcription="...")
    extract(state, client, CONFIG)
    assert state.extracted_fields == []


def test_extract_passes_transcription_to_client() -> None:
    client = MockLLMClient([])
    state = PipelineState(source_pdf=Path("x.pdf"), transcription="the text")
    extract(state, client, CONFIG)
    assert client.last_transcription == "the text"
