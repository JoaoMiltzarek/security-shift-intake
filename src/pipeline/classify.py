"""Stage 4 — Classify: report -> incident type / urgency / responsible sector.

LLM with structured output is the production path (spec §2): the taxonomy is small
and zero/few-shot is strong without labeled volume. A trained sklearn classifier is
the documented evolution path (M8), not this stage. Mockable via LLMClient.
"""

from __future__ import annotations

from src.clients.base import LLMClient
from src.schema.config import ReportConfig
from src.schema.state import Classification, PipelineState


def classify(state: PipelineState, client: LLMClient, config: ReportConfig) -> PipelineState:
    """Classify the transcription against the config taxonomy; return updated state."""
    taxonomy = config.classification
    result = client.classify(
        state.transcription or "",
        types=taxonomy.type.labels,
        urgencies=taxonomy.urgency.labels,
        sectors=taxonomy.sector.labels,
    )
    classification = Classification(
        incident_type=result.incident_type,
        urgency=result.urgency,
        sector=result.sector,
        confidence=result.confidence,
    )
    return state.model_copy(update={"classification": classification})
