"""Provider-agnostic vision client interface and result types.

Every model call in the pipeline goes through this interface so the provider is
swappable and, crucially, **mockable in tests** (spec §2 provider abstraction,
§8.4 mock the model layer). No raw API calls scattered through the codebase.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class TranscriptionResult(BaseModel):
    """Verbatim transcription of one page image, with model-reported confidence."""

    text: str
    confidence: float = Field(ge=0.0, le=1.0)


@runtime_checkable
class VisionClient(Protocol):
    """Reads a page image and returns a faithful transcription.

    Implementations: MockVisionClient (tests, $0) and AnthropicVisionClient (real).
    """

    def transcribe(self, image_b64: str, media_type: str = "image/png") -> TranscriptionResult:
        """Transcribe a base64-encoded page image verbatim."""
        ...
