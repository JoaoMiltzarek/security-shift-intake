"""PipelineState: the typed document that flows through every pipeline stage.

Each stage receives the current state and returns a new (or mutated) state.
Fields accumulate as the document progresses through the pipeline:
  Stage 0 (ingest)    → image_paths populated
  Stage 1 (transcribe)→ transcription + transcription_confidence populated
  Stage 2 (extract)   → extracted_fields populated
  Stage 3 (validate)  → validation_flags populated
  Stage 4 (classify)  → classification populated
  Stage 5 (route)     → recipients populated
  Stage 5 (draft)     → email_draft populated
  Stage 6 (gate)      → approval_status updated

All Optional fields start as None so the state can be constructed at ingest
time and enriched by each stage without forward-referencing incomplete data.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.clients.base import WordBox
from src.schema.evidence import BBox
from src.schema.extraction import (
    NormalizedIncidentModel,
    RawDocumentExtraction,
    SpreadsheetRow,
)


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ExtractedField(BaseModel):
    """One extracted field with its value and source-specific confidence signal.

    The signal may be OCR-derived, model-reported, or a fixed rule placeholder; it is not
    necessarily a calibrated probability. ``must_review`` is the operational gate.
    """

    name: str
    value: Any = None
    confidence: float = Field(ge=0.0, le=1.0)
    must_review: bool = False
    # Audit trail surfaced to the review UI: where the value came from
    # (ocr | rule | human) and the critic's status (accepted | must_review |
    # missing | ambiguous). Populated from the AuditedField on the table path;
    # None on the scalar path, where no AuditedField backs the field.
    source: str | None = None
    status: str | None = None
    # Evidence (PR2): where on the page this value most likely came from. bbox is a
    # *probable* region (fractions 0..1), never proof. None when the locator found no
    # match, the reader emitted no geometry, or a human edited the value.
    bbox: BBox | None = None
    page: int | None = None
    evidence_text: str | None = None
    evidence_method: str | None = None  # exact | token_window | none | human_edit
    evidence_score: float | None = Field(default=None, ge=0.0, le=1.0)


class Classification(BaseModel):
    """Structured output from the classify stage."""

    incident_type: str
    urgency: str
    sector: str
    # Raw model confidence — used by the critic to surface low-confidence results.
    confidence: float = Field(ge=0.0, le=1.0)
    # Why this classification (e.g. "OCR quality below threshold"); None on the normal path.
    reason: str | None = None


class PipelineState(BaseModel):
    """Typed state object passed through every stage of the pipeline."""

    # Identity of the validated report config that produced this state. The cockpit
    # rejects edits under a different config instead of silently reinterpreting data.
    report_type: str | None = None
    config_sha256: str | None = Field(default=None, min_length=64, max_length=64)

    # --- Stage 0: ingest ---
    source_pdf: Path
    image_paths: list[Path] = Field(default_factory=list)
    # Persisted OCR page images for the cockpit overlay, as POSIX paths relative to the
    # page-images root (the *same* downscaled image the words were measured on, so the
    # normalized boxes line up). Empty on paths that never persisted images.
    page_image_paths: list[str] = Field(default_factory=list)

    # --- Stage 1: transcribe ---
    transcription: str | None = None
    transcription_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    # Origin of the confidence, copied verbatim from TranscriptionResult (logprobs |
    # placeholder | tesseract | mock); the eval reads it here — never inferred.
    transcription_confidence_source: str | None = None
    # OCR word geometry (fractions 0..1) for the evidence locator; None on mock/VLM paths.
    words: list[WordBox] | None = None
    # --- OCR quality gate (table path) ---  good | low | failed
    ocr_quality: str | None = None
    ocr_quality_reason: str | None = None

    # --- Stage 2: extract ---
    extracted_fields: list[ExtractedField] = Field(default_factory=list)
    # Layout-coupled read and normalized occurrence domain model. Both remain optional
    # while a document is being ingested; review approval requires `normalized`.
    raw_extraction: RawDocumentExtraction | None = None
    normalized: NormalizedIncidentModel | None = None
    # --- Stage 3: validate (critic) ---
    # Field names that the critic flagged as MUST_REVIEW.
    must_review_fields: list[str] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)

    # --- Stage 4: classify ---
    classification: Classification | None = None

    # --- Stage 5: route + draft ---
    recipients: list[str] = Field(default_factory=list)
    email_draft: str | None = None
    # --- Outputs (table path): planilha padronizada + mensagem copy-ready ---
    spreadsheet_rows: list[SpreadsheetRow] = Field(default_factory=list)

    # --- Stage 6: human gate ---
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    # Audit trail — list of {actor, action, timestamp} dicts.
    audit_log: list[dict[str, str]] = Field(default_factory=list)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def exceeds_v1_page_scope(self) -> bool:
        """Detect persisted legacy states that predate the single-page v1 contract."""
        return (
            len(self.image_paths) > 1
            or len(self.page_image_paths) > 1
            or "\f" in (self.transcription or "")
        )
