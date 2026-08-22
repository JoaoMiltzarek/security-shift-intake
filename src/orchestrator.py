"""Explicit, table-only intake orchestration for the supported v1 product."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.classifier.contracts import IncidentClassifier
from src.clients.base import DocumentReader, RuntimeMetadataProvider
from src.pipeline.classify import classify
from src.pipeline.extract_table import extract_table
from src.pipeline.ingest import (
    DEFAULT_DPI,
    MAX_READER_LONG_SIDE,
    Deadline,
    PageArtifact,
    ProcessingDeadlineExceeded,
    load_page_artifacts,
)
from src.pipeline.ocr_quality import OCR_FAILED, assess_ocr_quality
from src.pipeline.transcribe import transcribe
from src.pipeline.validate import validate_table
from src.schema.config import ReportConfig
from src.schema.extraction import NormalizedIncidentModel, RawDocumentExtraction
from src.schema.loader import config_fingerprint
from src.schema.state import PipelineState, RasterSettings, ReaderSettings


@dataclass(frozen=True, slots=True)
class IntakeResult:
    """Final domain state plus the exact immutable pages reviewed by the reader."""

    state: PipelineState
    pages: tuple[PageArtifact, ...]


def _timeout_result(
    state: PipelineState,
    pages: tuple[PageArtifact, ...],
    config: ReportConfig,
    reason: str,
) -> IntakeResult:
    """Preserve completed stages and make incomplete structure explicitly unknown."""
    blocked = state.model_copy(update={"classification": None})
    if blocked.raw_extraction is None or blocked.normalized is None:
        blocked = blocked.model_copy(
            update={
                "raw_extraction": RawDocumentExtraction(
                    report_type=config.report_type,
                    tabela_encontrada=False,
                ),
                "normalized": NormalizedIncidentModel(),
                "extracted_fields": [],
                "must_review_fields": [],
            }
        )
        blocked = validate_table(blocked, config)

    validation_errors = list(dict.fromkeys([*blocked.validation_errors, reason]))
    updates: dict[str, object] = {"validation_errors": validation_errors}
    if blocked.ocr_quality is None:
        updates.update(
            {
                "ocr_quality": OCR_FAILED,
                "ocr_quality_reason": reason,
            }
        )
    blocked = blocked.model_copy(update=updates)
    return IntakeResult(state=blocked, pages=pages)


def run_pipeline(
    source: Path,
    reader: DocumentReader,
    classifier: IncidentClassifier,
    config: ReportConfig,
    dpi: int = DEFAULT_DPI,
) -> IntakeResult:
    """Run the single supported occurrence-sheet pipeline within one deadline."""
    budget_seconds = config.performance.max_seconds_per_sheet
    deadline = Deadline.after(budget_seconds)
    pages: tuple[PageArtifact, ...] = ()
    reader_runtime = (
        reader.runtime_metadata() if isinstance(reader, RuntimeMetadataProvider) else {}
    )
    state = PipelineState(
        source_pdf=source,
        report_type=config.report_type,
        config_sha256=config_fingerprint(config),
        reader_settings=ReaderSettings(
            adapter=f"{type(reader).__module__}.{type(reader).__qualname__}",
            runtime=reader_runtime,
        ),
        raster_settings=RasterSettings(
            dpi=dpi,
            max_long_side=MAX_READER_LONG_SIDE,
        ),
    )

    try:
        pages = load_page_artifacts(source, dpi=dpi, deadline=deadline)
        state = transcribe(state, reader, pages=pages, deadline=deadline)
        deadline.remaining_seconds(stage="table extraction")
        state = validate_table(extract_table(state, config), config)
        status, reason = assess_ocr_quality(state, config)
        state = state.model_copy(update={"ocr_quality": status, "ocr_quality_reason": reason})

        if status == OCR_FAILED:
            blocked = state.model_copy(update={"classification": None})
            return IntakeResult(state=blocked, pages=pages)

        deadline.remaining_seconds(stage="classification")
        state = classify(state, classifier, config)
        return IntakeResult(state=state, pages=pages)
    except ProcessingDeadlineExceeded as exc:
        return _timeout_result(state, pages, config, str(exc))
