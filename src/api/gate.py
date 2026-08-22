"""Revision-bound human approval and local simulation gate."""

from __future__ import annotations

import hmac
from pathlib import Path
from typing import Protocol, runtime_checkable

from sqlmodel import Session

from src.api.models import Draft
from src.api.readiness import ReadinessBlockerCode, ReadinessReport, evaluate_readiness
from src.api.repository import (
    _mark_simulated_locked,
    _set_status_locked,
    add_audit,
    draft_operation_lock,
    get_draft,
    state_sha256,
)
from src.pipeline.outputs import derive_operational_outputs
from src.schema.config import ReportConfig
from src.schema.state import ApprovalStatus, PipelineState


class DraftNotApprovedError(RuntimeError):
    """Raised when simulation is attempted without a current approval."""


class DraftNotReviewableError(RuntimeError):
    """Raised when a draft still contains unresolved review blockers."""


def _reviewability_error(report: ReadinessReport) -> DraftNotReviewableError:
    blocker_priority = (
        ReadinessBlockerCode.EVIDENCE_CHANGED,
        ReadinessBlockerCode.CONFIG_MISMATCH,
        ReadinessBlockerCode.FIELD_PENDING,
        ReadinessBlockerCode.VALIDATION_ERROR,
        ReadinessBlockerCode.DISPOSITION_UNCONFIRMED,
        ReadinessBlockerCode.CLASSIFICATION_UNCONFIRMED,
        ReadinessBlockerCode.ROUTING_UNRESOLVED,
    )
    blocker = next(
        item
        for code in blocker_priority
        for item in report.blockers
        if item.code == code
    )
    suffix = f" Fields: {', '.join(blocker.fields)}." if blocker.fields else ""
    return DraftNotReviewableError(f"{blocker.detail}{suffix}")


def assert_reviewable(
    state: PipelineState,
    config: ReportConfig | None = None,
    *,
    page_root: Path | None = None,
) -> None:
    """Compatibility guard backed by the centralized readiness calculation."""
    report = evaluate_readiness(state, config, page_root=page_root)
    if report.approvable:
        return
    raise _reviewability_error(report)


def approve_draft(
    session: Session,
    draft_id: int,
    config: ReportConfig,
    page_root: Path,
    *,
    expected_revision: int,
    expected_state_sha256: str,
    actor: str = "reviewer",
) -> Draft:
    """Approve only the snapshot whose full readiness was checked under its lock."""
    with draft_operation_lock(session, draft_id, wait=False):
        session.expire_all()
        draft = get_draft(session, draft_id)
        if draft is None:
            raise KeyError(f"Draft {draft_id} not found")
        digest = state_sha256(draft.state_json)
        if draft.revision != expected_revision or not hmac.compare_digest(
            digest, expected_state_sha256
        ):
            raise DraftNotReviewableError(
                "Draft changed after this review page was loaded. Reload before continuing."
            )
        state = PipelineState.from_persisted_json(draft.state_json)
        report = evaluate_readiness(state, config, page_root=page_root)
        if not report.approvable:
            raise _reviewability_error(report)
        return _set_status_locked(
            session,
            draft_id,
            ApprovalStatus.APPROVED,
            actor,
            expected_revision=expected_revision,
        )


@runtime_checkable
class SimulationRecorder(Protocol):
    """Observe the terminal local simulation without any delivery capability."""

    def simulate(self, recipients: list[str], body: str) -> None:
        """Record the would-be recipients and body in process memory only."""
        ...


class MemorySimulationRecorder:
    """In-memory simulation observer used by the local cockpit and tests."""

    def __init__(self) -> None:
        self.records: list[tuple[list[str], str]] = []

    @property
    def call_count(self) -> int:
        return len(self.records)

    def simulate(self, recipients: list[str], body: str) -> None:
        self.records.append((recipients, body))


def simulate_draft(
    session: Session,
    draft_id: int,
    recorder: SimulationRecorder,
    config: ReportConfig,
    actor: str = "reviewer",
    *,
    page_root: Path | None = None,
) -> Draft:
    """Serialize and record one terminal simulation for an approved snapshot."""
    with draft_operation_lock(session, draft_id, wait=True):
        session.expire_all()
        return _simulate_draft_once(
            session,
            draft_id,
            recorder,
            config,
            actor,
            page_root=page_root,
        )


def _simulate_draft_once(
    session: Session,
    draft_id: int,
    recorder: SimulationRecorder,
    config: ReportConfig,
    actor: str,
    *,
    page_root: Path | None,
) -> Draft:
    draft = get_draft(session, draft_id)
    if draft is None:
        raise KeyError(f"Draft {draft_id} not found")

    if draft.status != ApprovalStatus.APPROVED:
        add_audit(
            session,
            draft_id,
            actor=actor,
            action="simulation_blocked",
            detail=f"status={draft.status}",
        )
        raise DraftNotApprovedError(
            f"Draft {draft_id} is '{draft.status}', not approved — simulation blocked."
        )

    if draft.sent_at is not None:
        add_audit(
            session,
            draft_id,
            actor=actor,
            action="simulation_blocked",
            detail="already_simulated",
        )
        raise DraftNotApprovedError(f"Draft {draft_id} was already simulated.")

    state = PipelineState.from_persisted_json(draft.state_json)
    digest = state_sha256(draft.state_json)
    readiness = evaluate_readiness(
        state,
        config,
        page_root=page_root,
        status=draft.status,
        revision=draft.revision,
        state_sha256=digest,
        approved_revision=draft.approved_revision,
        approved_state_sha256=draft.approved_state_sha256,
    )
    if not readiness.simulatable:
        blocker = (
            readiness.blocker(ReadinessBlockerCode.APPROVAL_STALE)
            or readiness.blockers[0]
        )
        audit_detail: str = str(blocker.code)
        if blocker.code == ReadinessBlockerCode.APPROVAL_STALE:
            audit_detail = (
                f"stale_approval rev={draft.revision} "
                f"approved_rev={draft.approved_revision}"
            )
        add_audit(
            session,
            draft_id,
            actor=actor,
            action="simulation_blocked",
            detail=str(audit_detail),
        )
        raise DraftNotApprovedError(blocker.detail)

    derived = derive_operational_outputs(state, config)
    if derived.routing is None or derived.message is None:
        add_audit(
            session,
            draft_id,
            actor=actor,
            action="simulation_blocked",
            detail="routing_unresolved",
        )
        raise DraftNotApprovedError("Operational routing is unresolved.")
    recorder.simulate(derived.routing.recipients, derived.message)
    return _mark_simulated_locked(session, draft_id, actor=actor)
