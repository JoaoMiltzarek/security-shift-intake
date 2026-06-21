"""Stage 1 — Transcribe: VLM reads the page image(s) into verbatim text.

Kept as a separate stage from extraction (spec §2) for auditability and a
separable HTR eval. Rasterizes the PDF (stage 0), transcribes each page through
the provider-agnostic VisionClient, and writes the combined text + a conservative
confidence into the pipeline state. The input state is never mutated — a new state
is returned.
"""

from __future__ import annotations

from src.clients.base import VisionClient
from src.pipeline.ingest import DEFAULT_DPI, image_to_base64_png, rasterize_pdf
from src.schema.state import PipelineState

# Separator between page transcriptions in the combined text.
_PAGE_SEP = "\n\n"


def transcribe(
    state: PipelineState,
    client: VisionClient,
    dpi: int = DEFAULT_DPI,
) -> PipelineState:
    """Rasterize + transcribe the source PDF; return an updated PipelineState."""
    images = rasterize_pdf(state.source_pdf, dpi=dpi)
    results = [client.transcribe(image_to_base64_png(img)) for img in images]

    text = _PAGE_SEP.join(r.text for r in results)
    # Conservative aggregate: the least-confident page drives review (surfaces
    # uncertainty rather than hiding it behind an average).
    confidence = min((r.confidence for r in results), default=0.0)

    return state.model_copy(
        update={"transcription": text, "transcription_confidence": confidence}
    )
