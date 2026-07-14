"""Stage 4 — Classify: report -> incident type / urgency / responsible sector.

LLM with structured output is the production path (spec §2): the taxonomy is small
and zero/few-shot is strong without labeled volume. A trained sklearn classifier is
the documented evolution path (M8), not this stage. Mockable via LLMClient.
"""

from __future__ import annotations

from src.clients.base import LLMClient
from src.schema.config import ReportConfig
from src.schema.state import Classification, PipelineState


def classify(
    state: PipelineState,
    client: LLMClient,
    config: ReportConfig,
    text: str | None = None,
    reason: str | None = None,
) -> PipelineState:
    """Classify the transcription against the config taxonomy; return updated state.

    `text` (opcional) classifica um conteúdo canônico revisado no lugar da transcrição
    bruta — usado pelo re-classify pós-edição humana (SSI-1007); `reason` registra a
    procedência da classificação para o revisor.
    """
    taxonomy = config.classification
    result = client.classify(
        text if text is not None else (state.transcription or ""),
        types=taxonomy.type.labels,
        urgencies=taxonomy.urgency.labels,
        sectors=taxonomy.sector.labels,
    )
    invalid_dimensions = [
        dimension
        for dimension, value, allowed in (
            ("type", result.incident_type, taxonomy.type.labels),
            ("urgency", result.urgency, taxonomy.urgency.labels),
            ("sector", result.sector, taxonomy.sector.labels),
        )
        if value not in allowed
    ]
    if invalid_dimensions:
        raise ValueError(
            "classification output outside configured taxonomy: " + ", ".join(invalid_dimensions)
        )
    classification = Classification(
        incident_type=result.incident_type,
        urgency=result.urgency,
        sector=result.sector,
        confidence=result.confidence,
        reason=reason,
    )
    return state.model_copy(update={"classification": classification})
