"""One fail-closed readiness contract for every consequential draft action."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from src.api.page_images import PageArtifactIntegrityError, read_page_image
from src.pipeline.route import select_route
from src.schema.config import ReportConfig
from src.schema.loader import config_fingerprint
from src.schema.state import ApprovalStatus, PipelineState


class ReadinessBlockerCode(StrEnum):
    """Stable machine-readable reasons why an operation is unavailable."""

    EVIDENCE_CHANGED = "evidence_changed"
    CONFIG_MISMATCH = "config_mismatch"
    DISPOSITION_UNCONFIRMED = "disposition_unconfirmed"
    FIELD_PENDING = "field_pending"
    VALIDATION_ERROR = "validation_error"
    CLASSIFICATION_UNCONFIRMED = "classification_unconfirmed"
    ROUTING_UNRESOLVED = "routing_unresolved"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_STALE = "approval_stale"


class ReadinessBlocker(BaseModel):
    """A structured blocker safe to expose through the local API."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: ReadinessBlockerCode
    detail: str
    fields: list[str] = Field(default_factory=list)


class ReadinessReport(BaseModel):
    """Capabilities derived from the current bytes, state, config, and approval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approvable: bool
    exportable: bool
    simulatable: bool
    blockers: list[ReadinessBlocker] = Field(default_factory=list)

    def blocker(self, code: ReadinessBlockerCode) -> ReadinessBlocker | None:
        return next((blocker for blocker in self.blockers if blocker.code == code), None)


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _append_once(
    blockers: list[ReadinessBlocker],
    code: ReadinessBlockerCode,
    detail: str,
    *,
    fields: list[str] | None = None,
) -> None:
    if any(blocker.code == code for blocker in blockers):
        return
    blockers.append(ReadinessBlocker(code=code, detail=detail, fields=fields or []))


def _evidence_blocker(state: PipelineState, page_root: Path) -> str | None:
    if state.is_legacy:
        return "Legacy state has no v2 evidence identity; re-ingest the source document."
    if len(state.page_artifacts) != 1:
        return "The current v1 draft must reference exactly one verified page artifact."
    try:
        read_page_image(state.page_artifacts, 0, page_root)
    except (FileNotFoundError, PermissionError, PageArtifactIntegrityError, OSError):
        return "The page artifact is missing, unreadable, or differs from the ingested bytes."
    return None


def _pending_fields(state: PipelineState, config: ReportConfig | None) -> list[str]:
    pending = set(state.must_review_fields)
    pending.update(field.name for field in state.extracted_fields if field.must_review)
    pending.update(
        field.name
        for field in state.extracted_fields
        if field.status in {"missing", "must_review", "ambiguous"}
    )
    extracted = {field.name: field for field in state.extracted_fields}
    if config is not None:
        for field in config.fields:
            if not field.required or field.type == "table":
                continue
            value = extracted.get(field.name)
            if value is None or _blank(value.value):
                pending.add(field.name)
    normalized = state.normalized
    if normalized is not None:
        pending.update(
            f"ocorrencia_{index}"
            for index, occurrence in enumerate(normalized.occurrences, start=1)
            if occurrence.needs_review
        )
    if state.ocr_quality == "failed":
        pending.add("manual_transcription")
    return sorted(pending)


def evaluate_readiness(
    state: PipelineState,
    config: ReportConfig | None,
    *,
    page_root: Path | None = None,
    status: str | None = None,
    revision: int | None = None,
    state_sha256: str | None = None,
    approved_revision: int | None = None,
    approved_state_sha256: str | None = None,
) -> ReadinessReport:
    """Recalculate readiness without trusting a previously persisted capability.

    ``page_root=None`` is reserved for semantic-only callers such as offline
    evaluation. Every API operation passes a root and therefore verifies the exact
    evidence bytes. Approval fields are included only when ``status`` is supplied.
    """
    blockers: list[ReadinessBlocker] = []

    if page_root is not None:
        evidence_detail = _evidence_blocker(state, page_root)
        if evidence_detail is not None:
            _append_once(
                blockers,
                ReadinessBlockerCode.EVIDENCE_CHANGED,
                evidence_detail,
            )
    elif state.is_legacy or state.exceeds_v1_page_scope():
        _append_once(
            blockers,
            ReadinessBlockerCode.EVIDENCE_CHANGED,
            (
                "Legacy state has no supported single-page v2 evidence contract; "
                "re-ingest the source document."
            ),
        )

    if config is not None and (
        state.report_type != config.report_type
        or state.config_sha256 != config_fingerprint(config)
    ):
        _append_once(
            blockers,
            ReadinessBlockerCode.CONFIG_MISMATCH,
            "The draft was not produced by the active report configuration.",
        )

    normalized = state.normalized
    if (
        normalized is None
        or normalized.disposition == "unknown"
        or not normalized.disposition_confirmed
    ):
        disposition_detail = (
            "Draft does not contain the supported occurrence-sheet model."
            if normalized is None
            else "Occurrence disposition requires explicit human confirmation."
        )
        _append_once(
            blockers,
            ReadinessBlockerCode.DISPOSITION_UNCONFIRMED,
            disposition_detail,
        )

    pending = _pending_fields(state, config)
    if pending:
        _append_once(
            blockers,
            ReadinessBlockerCode.FIELD_PENDING,
            "One or more required fields need review by a human.",
            fields=pending,
        )

    if state.validation_errors:
        _append_once(
            blockers,
            ReadinessBlockerCode.VALIDATION_ERROR,
            "The current state contains validation errors.",
            fields=list(state.validation_errors),
        )

    classification = state.classification
    classification_allowed = False
    if normalized is not None and normalized.disposition != "unknown":
        if classification is not None:
            classification_allowed = config is None or (
                classification.incident_type in config.classification.type.labels
                and classification.urgency in config.classification.urgency.labels
                and classification.sector in config.classification.sector.labels
            )
        if (
            classification is None
            or classification.review_status != "confirmed"
            or not classification_allowed
        ):
            _append_once(
                blockers,
                ReadinessBlockerCode.CLASSIFICATION_UNCONFIRMED,
                "Classification must be confirmed under the active taxonomy.",
            )

    route_resolved = False
    if classification is not None and classification.review_status == "confirmed":
        if config is None:
            route_resolved = True
        else:
            routing = select_route(classification, config)
            route_resolved = bool(routing.recipients) if routing is not None else False
    if normalized is not None and normalized.disposition != "unknown" and not route_resolved:
        _append_once(
            blockers,
            ReadinessBlockerCode.ROUTING_UNRESOLVED,
            "No non-empty server-side route resolves for the confirmed classification.",
        )

    operational_codes = {
        ReadinessBlockerCode.EVIDENCE_CHANGED,
        ReadinessBlockerCode.CONFIG_MISMATCH,
        ReadinessBlockerCode.DISPOSITION_UNCONFIRMED,
        ReadinessBlockerCode.FIELD_PENDING,
        ReadinessBlockerCode.VALIDATION_ERROR,
        ReadinessBlockerCode.CLASSIFICATION_UNCONFIRMED,
        ReadinessBlockerCode.ROUTING_UNRESOLVED,
    }
    approvable = not any(blocker.code in operational_codes for blocker in blockers)

    approval_current = False
    if status is not None:
        if status != ApprovalStatus.APPROVED:
            _append_once(
                blockers,
                ReadinessBlockerCode.APPROVAL_REQUIRED,
                "The current revision requires human approval.",
            )
        elif (
            revision is None
            or state_sha256 is None
            or approved_revision != revision
            or approved_state_sha256 != state_sha256
        ):
            _append_once(
                blockers,
                ReadinessBlockerCode.APPROVAL_STALE,
                "Approval does not match the current revision and state hash.",
            )
        else:
            approval_current = True

    return ReadinessReport(
        approvable=approvable,
        exportable=approvable and approval_current,
        simulatable=approvable and approval_current,
        blockers=blockers,
    )
