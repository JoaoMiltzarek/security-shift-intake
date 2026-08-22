"""Local document-reader contracts and auditable OCR result types.

The product passes one canonical ``PageArtifact`` to a ``DocumentReader`` under the
sheet-wide deadline. Readers return text plus any geometry they can prove against
those exact bytes; deterministic fakes exercise the same boundary in tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from src.schema.evidence import BBox

if TYPE_CHECKING:
    from src.pipeline.ingest import Deadline, PageArtifact


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
    bbox: BBox
    conf: float = Field(ge=0.0, le=1.0)
    # block:par:line from Tesseract — distinguishes lines that share a line_num across
    # different blocks/paragraphs, so the token-window locator never merges them.
    line_key: str
    page: int = 0
    coordinate_space: Literal["ocr_image"] = "ocr_image"


class TranscriptionResult(BaseModel):
    """Verbatim transcription of one page image, with model-reported confidence.

    ``words`` is optional: Tesseract fills it with measured geometry, while readers
    without word geometry leave it ``None`` and the evidence locator does not run.
    """

    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    # Where ``confidence`` came from, copied from the reader rather than inferred
    # downstream. Production uses Tesseract; other labels keep historical evaluation
    # snapshots readable, and ``mock`` identifies deterministic test data.
    confidence_source: (
        Literal["logprobs", "placeholder", "tesseract", "paddleocr", "mock"] | None
    ) = None
    words: list[WordBox] | None = None
    # Pixel size of the image the words were measured against (for reconstruction).
    image_width: int | None = None
    image_height: int | None = None


@runtime_checkable
class DocumentReader(Protocol):
    """Read one canonical page within the intake's global monotonic deadline."""

    def read(self, page: PageArtifact, deadline: Deadline) -> TranscriptionResult:
        """Return faithful page transcription and evidence geometry."""
        ...


@runtime_checkable
class RuntimeMetadataProvider(Protocol):
    """Provides a sanitized, reproducibility-focused runtime identity."""

    def runtime_metadata(self) -> dict[str, str]:
        """Return safe metadata for the exact reader instance used by a run."""
        ...
