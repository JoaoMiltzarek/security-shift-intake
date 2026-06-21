"""AnthropicVisionClient — the real VLM transcription client.

Implements VisionClient against the Anthropic Messages API: a base64 image block
+ a transcription prompt, with structured output validated by the Pydantic
TranscriptionResult model (per the vlm-document-extraction skill).

Status: built against the verified Anthropic API shape (model id from config), but
**not yet validated against a live API in this environment** (no API key — the
project is mock-first). The mock client is used in all tests and CI ($0). When a
key is available, `make demo-transcribe FILE=...` exercises this path for real.
"""

from __future__ import annotations

from typing import Any

import anthropic

from src.clients.base import TranscriptionResult
from src.clients.settings import get_max_tokens, get_vision_model

_TRANSCRIPTION_PROMPT = (
    "You are transcribing a scanned, handwritten security shift-report form "
    "(Portuguese, Brazil). Transcribe the page VERBATIM: preserve the printed "
    "field labels and the handwritten values exactly as written, including "
    "abbreviations and apparent errors. Do not correct, summarise, or infer. "
    "Return the full transcription text and your overall confidence (0.0-1.0)."
)


class AnthropicVisionClient:
    """Real VisionClient backed by the Anthropic Messages API."""

    def __init__(
        self,
        client: anthropic.Anthropic | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> None:
        # anthropic.Anthropic() reads ANTHROPIC_API_KEY from the env and raises a
        # clear error at construction if it is missing — no network call here.
        self._client = client or anthropic.Anthropic()
        self._model = model or get_vision_model()
        self._max_tokens = max_tokens or get_max_tokens()

    def transcribe(self, image_b64: str, media_type: str = "image/png") -> TranscriptionResult:
        # Typed as Any at the SDK boundary: the block shape is verified against the
        # Anthropic vision API docs, but mypy can't narrow `media_type` to the
        # Literal the SDK's ImageBlockParam expects.
        message: Any = {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_b64,
                    },
                },
                {"type": "text", "text": _TRANSCRIPTION_PROMPT},
            ],
        }
        response = self._client.messages.parse(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=[message],
            output_format=TranscriptionResult,
        )
        result = response.parsed_output
        if result is None:
            raise RuntimeError("Model did not return a parseable TranscriptionResult.")
        return result
