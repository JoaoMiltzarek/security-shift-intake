"""PipelineState: the typed document that flows through every pipeline stage.

Each stage receives the current state and returns a new (or mutated) state.
Fields accumulate as the document progresses through the pipeline:
  Stage 0 (ingest)    → immutable page_artifacts populated
  Stage 1 (transcribe)→ transcription + transcription_confidence populated
  Stage 2 (extract)   → extracted_fields populated
  Stage 3 (validate)  → validation_flags populated
  Stage 4 (classify)  → classification populated
  Review decisions are persisted; route and output previews are derived on demand.

All Optional fields start as None so the state can be constructed at ingest
time and enriched by each stage without forward-referencing incomplete data.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.clients.base import WordBox
from src.schema.evidence import BBox, PageArtifactRef
from src.schema.extraction import (
    NormalizedIncidentModel,
    RawDocumentExtraction,
)


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SIMULATED = "simulated"


class UnsupportedPipelineStateVersionError(ValueError):
    """A persisted snapshot uses a schema this build must not reinterpret."""


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


class ClassificationDecision(BaseModel):
    """Auditable triage suggestion or explicit human decision."""

    model_config = ConfigDict(extra="forbid")

    incident_type: str
    urgency: str
    sector: str
    source: Literal["rule", "human"]
    review_status: Literal["suggested", "confirmed"]
    classification_rule_id: str | None = None

    @model_validator(mode="after")
    def _validate_provenance(self) -> Self:
        if self.source == "rule" and not self.classification_rule_id:
            raise ValueError("rule classification requires classification_rule_id")
        if self.source == "human" and self.classification_rule_id is not None:
            raise ValueError("human override cannot claim a classification rule id")
        if self.review_status == "suggested" and self.source != "rule":
            raise ValueError("only a rule decision can remain suggested")
        return self


Classification = ClassificationDecision


class RoutingDecision(BaseModel):
    """Server-derived recipient selection tied to one stable config rule."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str = Field(min_length=1)
    recipients: list[str] = Field(min_length=1)


class ReaderSettings(BaseModel):
    """Sanitized identity of the document reader used for this intake."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    adapter: str = Field(min_length=1)
    runtime: dict[str, str] = Field(default_factory=dict)


class RasterSettings(BaseModel):
    """Exact raster request that produced the immutable review surface."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dpi: int = Field(gt=0)
    max_long_side: int = Field(gt=0)
    output_format: Literal["png"] = "png"
    color_mode: Literal["RGB"] = "RGB"


class LegacyEvidenceMetadata(BaseModel):
    """Non-sensitive shape metadata retained from untrusted path-only evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_image_count: int = Field(default=0, ge=0)
    stored_page_count: int = Field(default=0, ge=0)


class PipelineState(BaseModel):
    """Typed state object passed through every stage of the pipeline."""

    schema_version: Literal["2.0"] = "2.0"
    # Set only by ``from_persisted_json`` when an unversioned/v1 snapshot is opened.
    # Keeping the marker in subsequent snapshots prevents an edit from laundering
    # legacy evidence into a state that can be approved.
    legacy_source_version: str | None = None
    # Legacy snapshots stored loose paths without hashes or dimensions. The loader
    # discards those values and retains only counts so the old shape remains visible
    # without turning any historical path into trusted evidence.
    legacy_evidence: LegacyEvidenceMetadata | None = None

    # Identity of the validated report config that produced this state. The cockpit
    # rejects edits under a different config instead of silently reinterpreting data.
    report_type: str | None = None
    config_sha256: str | None = Field(default=None, min_length=64, max_length=64)

    # --- Stage 0: ingest ---
    source_pdf: Path
    # Immutable identity of the exact reader-sized images used for OCR and review.
    page_artifacts: list[PageArtifactRef] = Field(default_factory=list, max_length=1)
    reader_settings: ReaderSettings | None = None
    raster_settings: RasterSettings | None = None

    # --- Stage 1: transcribe ---
    transcription: str | None = None
    transcription_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    # Origin of the confidence, copied verbatim from TranscriptionResult (logprobs |
    # placeholder | tesseract | mock); the eval reads it here — never inferred.
    transcription_confidence_source: str | None = None
    # OCR word geometry (fractions 0..1) for the evidence locator; absent when a reader
    # cannot provide measured word boxes.
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
    classification: ClassificationDecision | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    @model_validator(mode="after")
    def _validate_identity(self) -> Self:
        if (self.report_type is None) != (self.config_sha256 is None):
            raise ValueError("report_type and config_sha256 must be set together")
        if self.legacy_source_version == self.schema_version:
            raise ValueError("legacy_source_version cannot identify the current schema")
        if self.legacy_evidence is not None and not self.is_legacy:
            raise ValueError("legacy_evidence requires a legacy_source_version")
        return self

    @property
    def is_legacy(self) -> bool:
        """Whether this state originated before the strict v2 contract."""
        return self.legacy_source_version is not None

    @classmethod
    def from_persisted_json(cls, payload: str) -> PipelineState:
        """Load a stored snapshot without silently upgrading its trust level.

        Historical snapshots were unversioned. Their known fields remain readable
        for the review UI, while ``legacy_source_version`` keeps every operational
        gate fail-closed until the source document is ingested again.
        """
        raw = json.loads(payload)
        if not isinstance(raw, dict):
            raise ValueError("persisted pipeline state must be a JSON object")
        version = raw.get("schema_version")
        if version != "2.0":
            if version not in {None, "1.0", "1.1"}:
                raise UnsupportedPipelineStateVersionError(
                    f"unsupported persisted pipeline schema version: {version!r}"
                )
            raw["legacy_source_version"] = str(version or "unversioned")
            raw["schema_version"] = "2.0"
            # A path alone cannot establish evidence integrity. Legacy images remain
            # on disk but are deliberately reduced to non-sensitive count metadata,
            # never promoted into trusted v2 references.
            image_paths = raw.pop("image_paths", [])
            page_image_paths = raw.pop("page_image_paths", [])
            raw.pop("page_artifacts", None)
            raw["legacy_evidence"] = {
                "source_image_count": len(image_paths) if isinstance(image_paths, list) else 0,
                "stored_page_count": (
                    len(page_image_paths) if isinstance(page_image_paths, list) else 0
                ),
            }
            raw.pop("recipients", None)
            raw.pop("email_draft", None)
            raw.pop("spreadsheet_rows", None)
            raw.pop("reconcile_results", None)
            raw.pop("approval_status", None)
            raw.pop("audit_log", None)
            classification = raw.get("classification")
            if isinstance(classification, dict):
                migrated_classification = dict(classification)
                migrated_classification.pop("confidence", None)
                migrated_classification.pop("reason", None)
                migrated_classification.setdefault("source", "rule")
                migrated_classification.setdefault("review_status", "suggested")
                migrated_classification.setdefault("classification_rule_id", "legacy.unverified")
                raw["classification"] = migrated_classification
        return cls.model_validate(raw)

    def exceeds_v1_page_scope(self) -> bool:
        """Detect persisted legacy states that predate the single-page v1 contract."""
        legacy_page_count = 0
        if self.legacy_evidence is not None:
            legacy_page_count = max(
                self.legacy_evidence.source_image_count,
                self.legacy_evidence.stored_page_count,
            )
        return (
            legacy_page_count > 1
            or len(self.page_artifacts) > 1
            or "\f" in (self.transcription or "")
        )
