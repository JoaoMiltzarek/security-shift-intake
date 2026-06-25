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
    """One extracted field with its value and the model's confidence score."""

    name: str
    value: Any = None
    confidence: float = Field(ge=0.0, le=1.0)
    must_review: bool = False


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

    # --- Stage 0: ingest ---
    source_pdf: Path
    image_paths: list[Path] = Field(default_factory=list)

    # --- Stage 1: transcribe ---
    transcription: str | None = None
    transcription_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    # --- OCR quality gate (table path) ---  good | low | failed
    ocr_quality: str | None = None
    ocr_quality_reason: str | None = None

    # --- Stage 2: extract ---
    extracted_fields: list[ExtractedField] = Field(default_factory=list)
    # Table-report path (ADR controle_ocorrencias): the layout-coupled read and the
    # normalized domain model. None on the scalar path (htmicron_security).
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
