"""Data-access functions for drafts and the audit log.

Thin, explicit functions over a SQLModel Session. Every state-changing operation
writes an audit row so the approval history is always reconstructable.
"""

from __future__ import annotations

from sqlmodel import Session, col, select

from src.api.models import AuditEntry, Draft, utcnow
from src.schema.state import ApprovalStatus, PipelineState


def _require(session: Session, draft_id: int) -> Draft:
    draft = session.get(Draft, draft_id)
    if draft is None:
        raise KeyError(f"Draft {draft_id} not found")
    return draft


def add_audit(
    session: Session, draft_id: int, actor: str, action: str, detail: str | None = None
) -> AuditEntry:
    entry = AuditEntry(draft_id=draft_id, actor=actor, action=action, detail=detail)
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def create_draft(session: Session, state: PipelineState, actor: str = "system") -> Draft:
    """Persist a new pending draft from a PipelineState and audit the submission."""
    draft = Draft(status=ApprovalStatus.PENDING, state_json=state.model_dump_json())
    session.add(draft)
    session.commit()
    session.refresh(draft)
    assert draft.id is not None
    add_audit(session, draft.id, actor=actor, action="submitted")
    return draft


def get_draft(session: Session, draft_id: int) -> Draft | None:
    return session.get(Draft, draft_id)


def list_drafts(session: Session) -> list[Draft]:
    return list(session.exec(select(Draft).order_by(col(Draft.created_at))))


def set_status(session: Session, draft_id: int, status: ApprovalStatus, actor: str) -> Draft:
    """Update a draft's status and write an audit row."""
    draft = _require(session, draft_id)
    draft.status = status
    draft.updated_at = utcnow()
    session.add(draft)
    session.commit()
    session.refresh(draft)
    add_audit(session, draft_id, actor=actor, action=f"status:{status}")
    return draft


def mark_sent(session: Session, draft_id: int, actor: str) -> Draft:
    """Record that a draft was sent (sets sent_at + audit). The gate enforces policy."""
    draft = _require(session, draft_id)
    draft.sent_at = utcnow()
    session.add(draft)
    session.commit()
    session.refresh(draft)
    add_audit(session, draft_id, actor=actor, action="sent")
    return draft


def update_state(
    session: Session, draft_id: int, state: PipelineState, actor: str, action: str = "edited"
) -> Draft:
    """Replace a draft's stored PipelineState (e.g. after human edits) + audit."""
    draft = _require(session, draft_id)
    draft.state_json = state.model_dump_json()
    draft.updated_at = utcnow()
    session.add(draft)
    session.commit()
    session.refresh(draft)
    add_audit(session, draft_id, actor=actor, action=action)
    return draft


def get_audit(session: Session, draft_id: int) -> list[AuditEntry]:
    return list(
        session.exec(
            select(AuditEntry)
            .where(col(AuditEntry.draft_id) == draft_id)
            .order_by(col(AuditEntry.id))
        )
    )
