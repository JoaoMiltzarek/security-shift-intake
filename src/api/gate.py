"""Revision-bound human approval and local simulation gate."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from sqlmodel import Session

from src.api.models import Draft
from src.api.readiness import ReadinessBlockerCode, evaluate_readiness
from src.api.repository import (
    _mark_simulated_locked,
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
    operational_codes = {
        ReadinessBlockerCode.EVIDENCE_CHANGED,
        ReadinessBlockerCode.CONFIG_MISMATCH,
        ReadinessBlockerCode.DISPOSITION_UNCONFIRMED,
        ReadinessBlockerCode.FIELD_PENDING,
        ReadinessBlockerCode.VALIDATION_ERROR,
        ReadinessBlockerCode.CLASSIFICATION_UNCONFIRMED,
        ReadinessBlockerCode.ROUTING_UNRESOLVED,
    }
    blocker = next(item for item in report.blockers if item.code in operational_codes)
    suffix = f" Fields: {', '.join(blocker.fields)}." if blocker.fields else ""
    raise DraftNotReviewableError(f"{blocker.detail}{suffix}")


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
) -> Draft:
    """Serialize and record one terminal simulation for an approved snapshot."""
    with draft_operation_lock(session, draft_id, wait=True):
        session.expire_all()
        return _simulate_draft_once(session, draft_id, recorder, config, actor)


def _simulate_draft_once(
    session: Session,
    draft_id: int,
    recorder: SimulationRecorder,
    config: ReportConfig,
    actor: str,
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

    if draft.approved_revision != draft.revision or draft.approved_state_sha256 != state_sha256(
        draft.state_json
    ):
        add_audit(
            session,
            draft_id,
            actor=actor,
            action="simulation_blocked",
            detail=(f"stale_approval rev={draft.revision} approved_rev={draft.approved_revision}"),
        )
        raise DraftNotApprovedError(
            f"Draft {draft_id} content is not the approved revision — simulation blocked; "
            "re-approve the current content."
        )

    state = PipelineState.from_persisted_json(draft.state_json)
    try:
        assert_reviewable(state)
    except DraftNotReviewableError as exc:
        add_audit(
            session,
            draft_id,
            actor=actor,
            action="simulation_blocked",
            detail="not_reviewable",
        )
        raise DraftNotApprovedError(str(exc)) from exc

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
