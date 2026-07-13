"""AnthropicLLMClient — experimental structured-extraction adapter.

Implements LLMClient against the Anthropic Messages API with structured output
(`ExtractionResponse` validated by Pydantic, per the vlm-document-extraction
skill). Extracts the requested fields from a transcription, each with a value and
a confidence.

Status: EXPERIMENTAL paid external adapter, outside v1. No official entrypoint constructs it.
Tests use a fake SDK and do not prove live integration, HTTP failure handling, or suitability
for real PII.
"""

from __future__ import annotations

from typing import Any

import anthropic

from src.clients.base import ClassificationResult, ExtractedFieldRaw, ExtractionResponse
from src.clients.settings import get_max_tokens, get_vision_model


def _build_extract_prompt(transcription: str, field_names: list[str]) -> str:
    fields = "\n".join(f"- {name}" for name in field_names)
    return (
        "Extract the following fields from this transcribed security shift report. "
        "For each field return its value exactly as written (or null if absent) and "
        "your confidence (0.0-1.0). Do not invent values.\n\n"
        f"Fields:\n{fields}\n\n"
        f"Transcription:\n{transcription}"
    )


def _build_classify_prompt(
    transcription: str, types: list[str], urgencies: list[str], sectors: list[str]
) -> str:
    return (
        "Classify this security shift report. Choose exactly one label from each "
        "set and report your confidence (0.0-1.0).\n\n"
        f"incident_type: {types}\n"
        f"urgency: {urgencies}\n"
        f"sector: {sectors}\n\n"
        f"Transcription:\n{transcription}"
    )


class AnthropicLLMClient:
    """Unwired external LLMClient adapter for explicit experiments only."""

    def __init__(
        self,
        client: anthropic.Anthropic | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self._client = client or anthropic.Anthropic()
        self._model = model or get_vision_model()
        self._max_tokens = max_tokens or get_max_tokens()

    def extract_fields(self, transcription: str, field_names: list[str]) -> list[ExtractedFieldRaw]:
        message: Any = {
            "role": "user",
            "content": _build_extract_prompt(transcription, field_names),
        }
        response = self._client.messages.parse(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=[message],
            output_format=ExtractionResponse,
        )
        result = response.parsed_output
        if result is None:
            raise RuntimeError("Model did not return a parseable ExtractionResponse.")
        return result.fields

    def classify(
        self,
        transcription: str,
        types: list[str],
        urgencies: list[str],
        sectors: list[str],
    ) -> ClassificationResult:
        message: Any = {
            "role": "user",
            "content": _build_classify_prompt(transcription, types, urgencies, sectors),
        }
        response = self._client.messages.parse(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=[message],
            output_format=ClassificationResult,
        )
        result = response.parsed_output
        if result is None:
            raise RuntimeError("Model did not return a parseable ClassificationResult.")
        return result
