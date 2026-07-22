"""Stage 1 — read immutable page artifacts into verbatim text.

Kept as a separate stage from extraction (spec §2) for auditability and a
separable HTR eval. Ingestion already created the canonical PNG bytes, so this
stage only invokes the provider-agnostic DocumentReader and aggregates results.
"""

from __future__ import annotations

from collections.abc import Sequence

from src.clients.base import DocumentReader, WordBox
from src.pipeline.ingest import DEFAULT_DPI, Deadline, PageArtifact, load_page_artifacts
from src.schema.state import PipelineState

# Standard form-feed keeps page boundaries explicit for downstream table parsing.
_PAGE_SEP = "\n\f\n"


def transcribe(
    state: PipelineState,
    reader: DocumentReader,
    pages: Sequence[PageArtifact] | None = None,
    deadline: Deadline | None = None,
    *,
    dpi: int = DEFAULT_DPI,
) -> PipelineState:
    """Read canonical pages and return an updated state without mutating the input."""
    active_deadline = deadline or Deadline.after(300.0)
    active_pages = (
        pages
        if pages is not None
        else load_page_artifacts(state.source_pdf, dpi=dpi, deadline=active_deadline)
    )
    results = []
    for page in active_pages:
        active_deadline.remaining_seconds(stage="document reading")
        results.append(reader.read(page, active_deadline))

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
