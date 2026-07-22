"""Pipeline orchestrator — runs the staged pipeline end to end.

A typed function pipeline + explicit orchestrator (spec §2): no agents, no hidden control flow.
The interfaces are provider-agnostic, but supported v1 entrypoints pass local Tesseract +
deterministic rules; experimental external adapters require manual injection.

    ingest+transcribe → extract → validate (critic) → classify → route → draft
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.classifier.contracts import IncidentClassifier
from src.clients.base import DocumentReader
from src.pipeline.classify import classify
from src.pipeline.draft import blocked_draft_message, draft
from src.pipeline.extract import extract
from src.pipeline.extract_table import extract_table
from src.pipeline.ingest import (
    DEFAULT_DPI,
    Deadline,
    PageArtifact,
    ProcessingDeadlineExceeded,
    load_page_artifacts,
)
from src.pipeline.ocr_quality import OCR_FAILED, assess_ocr_quality
from src.pipeline.outputs import build_outputs
from src.pipeline.route import route
from src.pipeline.transcribe import transcribe
from src.pipeline.validate import validate, validate_table
from src.schema.config import ReportConfig
from src.schema.loader import config_fingerprint
from src.schema.state import Classification, PipelineState


@dataclass(frozen=True, slots=True)
class IntakeResult:
    """Final domain state plus the exact immutable pages reviewed by the reader."""

    state: PipelineState
    pages: tuple[PageArtifact, ...]


def _has_table(config: ReportConfig) -> bool:
    """True if the config declares a repeating table field (controle_ocorrencias)."""
    return any(f.type == "table" for f in config.fields)


def _timeout_result(
    state: PipelineState,
    pages: tuple[PageArtifact, ...],
    config: ReportConfig,
    reason: str,
) -> IntakeResult:
    """Create an auditable, structurally unknown draft after a deadline failure."""
    blocked = state.model_copy(
        update={
            "transcription": "",
            "transcription_confidence": 0.0,
            "ocr_quality": OCR_FAILED,
            "ocr_quality_reason": reason,
            "validation_errors": [*state.validation_errors, reason],
        }
    )
    if _has_table(config):
        blocked = validate_table(extract_table(blocked, config), config)
    blocked = blocked.model_copy(
        update={
            "ocr_quality": OCR_FAILED,
            "ocr_quality_reason": reason,
            "classification": Classification(
                incident_type="unknown",
                urgency="unknown",
                sector="manual_review",
                confidence=0.0,
                reason=reason,
            ),
        }
    )
    blocked = route(blocked, config)
    blocked = blocked.model_copy(update={"email_draft": blocked_draft_message(reason)})
    return IntakeResult(state=blocked, pages=pages)


def run_pipeline(
    source: Path,
    vision: DocumentReader,
    classifier: IncidentClassifier,
    config: ReportConfig,
    dpi: int = DEFAULT_DPI,
) -> IntakeResult:
    """Run all stages and return state plus the exact page artifacts (not persisted).

    The extract/validate pair is chosen by config: the deterministic table path
    (extract_table → validate_table, ADR controle_ocorrencias) when a table field is
    declared, otherwise the scalar path (extract → validate). Classify/route/draft are
    shared and config-driven.
    """
    budget_seconds = config.performance.max_seconds_per_sheet if config.performance else 300.0
    deadline = Deadline.after(budget_seconds)
    pages: tuple[PageArtifact, ...] = ()
    state = PipelineState(
        source_pdf=source,
        report_type=config.report_type,
        config_sha256=config_fingerprint(config),
    )
    try:
        pages = load_page_artifacts(source, dpi=dpi, deadline=deadline)
        state = transcribe(state, vision, pages=pages, deadline=deadline)

        if _has_table(config):
            deadline.remaining_seconds(stage="table extraction")
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
                blocked = state.model_copy(update={"email_draft": blocked_draft_message(reason)})
                return IntakeResult(state=blocked, pages=pages)
            deadline.remaining_seconds(stage="classification")
            state = classify(state, classifier, config)
            state = route(state, config)
            # Outputs do produto: planilha padronizada + mensagem copy-ready.
            return IntakeResult(state=build_outputs(state, config), pages=pages)

        # Caminho escalar (htmicron_security) — preservado para não-regressão.
        deadline.remaining_seconds(stage="scalar extraction")
        state = extract(state, classifier, config)  # type: ignore[arg-type]
        state = validate(state, config)
        state = classify(state, classifier, config)
        state = route(state, config)
        state = draft(state, config)
        return IntakeResult(state=state, pages=pages)
    except ProcessingDeadlineExceeded as exc:
        return _timeout_result(state, pages, config, str(exc))
