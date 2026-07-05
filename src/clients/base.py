"""Provider-agnostic vision client interface and result types.

Every model call in the pipeline goes through this interface so the provider is
swappable and, crucially, **mockable in tests** (spec §2 provider abstraction,
§8.4 mock the model layer). No raw API calls scattered through the codebase.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class WordBox(BaseModel):
    """One OCR word with its geometry, in **fractions 0..1** of the source image.

    The geometry is what makes a field's value auditable in the cockpit: we can point
    at *where on the page* the OCR text that produced the value sits. Coordinates are
    normalized so the overlay scales to any display size. `coordinate_space` is a
    closed enum on purpose — a box only ever lives in the OCR image space until code
    that maps to the original page exists.
    """

    text: str
    # (x0, y0, x1, y1) as fractions 0..1 of the source image (top-left origin).
    bbox: tuple[float, float, float, float]
    conf: float = Field(ge=0.0, le=1.0)
    # block:par:line from Tesseract — distinguishes lines that share a line_num across
    # different blocks/paragraphs, so the token-window locator never merges them.
    line_key: str
    page: int = 0
    coordinate_space: Literal["ocr_image"] = "ocr_image"


class TranscriptionResult(BaseModel):
    """Verbatim transcription of one page image, with model-reported confidence.

    `words` is optional and provider-specific: the local OCR path fills it (geometry
    from Tesseract); the mock/VLM paths leave it None and the evidence locator simply
    does not run (backward compatible).
    """

    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    words: list[WordBox] | None = None
    # Pixel size of the image the words were measured against (for reconstruction).
    image_width: int | None = None
    image_height: int | None = None


@runtime_checkable
class VisionClient(Protocol):
    """Reads a page image and returns a faithful transcription.

    Implementations: MockVisionClient (tests, $0) and AnthropicVisionClient (real).
    """

    def transcribe(self, image_b64: str, media_type: str = "image/png") -> TranscriptionResult:
        """Transcribe a base64-encoded page image verbatim."""
        ...


class ExtractedFieldRaw(BaseModel):
    """One field extracted from the transcription: raw string value + confidence.

    Values are raw strings (or null when blank/absent). Type coercion and validity
    checks happen deterministically in the critic stage, not here.
    """

    name: str
    value: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractionResponse(BaseModel):
    """Structured-output wrapper the LLM fills (one entry per requested field)."""

    fields: list[ExtractedFieldRaw]


class ClassificationResult(BaseModel):
    """Structured classification output: type / urgency / sector + confidence."""

    incident_type: str
    urgency: str
    sector: str
    confidence: float = Field(ge=0.0, le=1.0)


@runtime_checkable
class LLMClient(Protocol):
    """Extracts structured fields and classifies a transcription.

    Implementations: MockLLMClient (tests, $0) and AnthropicLLMClient (real).
    """

    def extract_fields(self, transcription: str, field_names: list[str]) -> list[ExtractedFieldRaw]:
        """Return one ExtractedFieldRaw per requested field name."""
        ...

    def classify(
        self,
        transcription: str,
        types: list[str],
        urgencies: list[str],
        sectors: list[str],
    ) -> ClassificationResult:
        """Classify the report into one label from each taxonomy dimension."""
        ...
