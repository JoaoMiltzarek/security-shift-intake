"""Pipeline orchestrator — runs the staged pipeline end to end.

A typed function pipeline + explicit orchestrator (spec §2): no agents, no hidden control flow.
The interfaces are provider-agnostic, but supported v1 entrypoints pass local Tesseract +
deterministic rules; experimental external adapters require manual injection.

    ingest+transcribe → extract → validate (critic) → classify → route → draft
"""

from __future__ import annotations

from pathlib import Path

from src.clients.base import DocumentReader, LLMClient
from src.pipeline.classify import classify
from src.pipeline.draft import blocked_draft_message, draft
from src.pipeline.extract import extract
from src.pipeline.extract_table import extract_table
from src.pipeline.ingest import DEFAULT_DPI
from src.pipeline.ocr_quality import OCR_FAILED, assess_ocr_quality
from src.pipeline.outputs import build_outputs
from src.pipeline.route import route
from src.pipeline.transcribe import transcribe
from src.pipeline.validate import validate, validate_table
from src.schema.config import ReportConfig
from src.schema.loader import config_fingerprint
from src.schema.state import Classification, PipelineState


def _has_table(config: ReportConfig) -> bool:
    """True if the config declares a repeating table field (controle_ocorrencias)."""
    return any(f.type == "table" for f in config.fields)


def run_pipeline(
    source: Path,
    vision: DocumentReader,
    llm: LLMClient,
    config: ReportConfig,
    dpi: int = DEFAULT_DPI,
) -> PipelineState:
    """Run all stages on *source* and return the final PipelineState (not persisted).

    The extract/validate pair is chosen by config: the deterministic table path
    (extract_table → validate_table, ADR controle_ocorrencias) when a table field is
    declared, otherwise the scalar path (extract → validate). Classify/route/draft are
    shared and config-driven.
    """
    state = PipelineState(
        source_pdf=source,
        report_type=config.report_type,
        config_sha256=config_fingerprint(config),
    )
    state = transcribe(state, vision, dpi=dpi)

    if _has_table(config):
        state = extract_table(state, config)
        state = validate_table(state, config)
        status, reason = assess_ocr_quality(state, config)
        state = state.model_copy(update={"ocr_quality": status, "ocr_quality_reason": reason})
        if status == OCR_FAILED:
            # Modo seguro: sem classificação automática nem rascunho operacional.
            state = state.model_copy(
                update={
                    "classification": Classification(
                        incident_type="unknown",
                        urgency="unknown",
                        sector="manual_review",
                        confidence=0.0,
                        reason=reason,
                    )
                }
            )
            state = route(state, config)
            return state.model_copy(update={"email_draft": blocked_draft_message(reason)})
        state = classify(state, llm, config)
        state = route(state, config)
        # Outputs do produto: planilha padronizada + mensagem copy-ready (bloqueia se pendente).
        return build_outputs(state, config)

    # Caminho escalar (htmicron_security) — preservado para não-regressão.
    state = extract(state, llm, config)
    state = validate(state, config)
    state = classify(state, llm, config)
    state = route(state, config)
    state = draft(state, config)
    return state
