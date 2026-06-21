"""Stage 2 — Extract: transcription -> structured fields (per the config schema).

Runs the configured field set through the provider-agnostic LLMClient and writes
the results (value + per-field confidence) into the pipeline state. Type validity
and MUST_REVIEW flagging are the critic's job (stage 3), not this stage's — here we
only capture what the model extracted.
"""

from __future__ import annotations

from src.clients.base import LLMClient
from src.schema.config import ReportConfig
from src.schema.state import ExtractedField, PipelineState


def extract(state: PipelineState, client: LLMClient, config: ReportConfig) -> PipelineState:
    """Extract the configured fields from the transcription; return updated state."""
    field_names = [f.name for f in config.fields]
    raw = client.extract_fields(state.transcription or "", field_names)

    extracted = [
        ExtractedField(name=r.name, value=r.value, confidence=r.confidence) for r in raw
    ]
    return state.model_copy(update={"extracted_fields": extracted})
