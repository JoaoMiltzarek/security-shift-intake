"""Stage 1 — Transcribe: VLM reads the page image(s) into verbatim text.

Kept as a separate stage from extraction (spec §2) for auditability and a
separable HTR eval. Loads the source (PDF or image, stage 0), transcribes each
page through the provider-agnostic VisionClient, and writes the combined text + a
conservative confidence into the pipeline state. The input state is never mutated
— a new state is returned.
"""

from __future__ import annotations

from src.clients.base import VisionClient, WordBox
from src.pipeline.ingest import DEFAULT_DPI, image_to_base64_png, load_source_images
from src.schema.state import PipelineState

# Separator between page transcriptions in the combined text.
_PAGE_SEP = "\n\n"


def transcribe(
    state: PipelineState,
    client: VisionClient,
    dpi: int = DEFAULT_DPI,
) -> PipelineState:
    """Load + transcribe the source (PDF or image); return an updated PipelineState."""
    images = load_source_images(state.source_pdf, dpi=dpi)
    try:
        results = [client.transcribe(image_to_base64_png(img)) for img in images]
    finally:
        for image in images:
            image.close()

    text = _PAGE_SEP.join(r.text for r in results)
    # Conservative aggregate: the least-confident page drives review (surfaces
    # uncertainty rather than hiding it behind an average).
    confidence = min((r.confidence for r in results), default=0.0)

    # Carry OCR geometry forward (stamped with the page index) so the evidence
    # locator can place each value on the right page. None unless a reader emits it.
    words: list[WordBox] | None = None
    for page_idx, result in enumerate(results):
        if result.words is None:
            continue
        if words is None:
            words = []
        words.extend(w.model_copy(update={"page": page_idx}) for w in result.words)

    return state.model_copy(
        update={
            "transcription": text,
            "transcription_confidence": confidence,
            "transcription_confidence_source": (results[0].confidence_source if results else None),
            "words": words,
        }
    )
