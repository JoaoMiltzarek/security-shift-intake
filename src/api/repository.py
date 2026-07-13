"""Data-access functions for drafts and the audit log.

Thin, explicit functions over a SQLModel Session. Every state-changing operation
writes an audit row so the approval history is always reconstructable.

Vínculo aprovação↔conteúdo (SSI-1006): o hash é SEMPRE calculado sobre o string
`state_json` exatamente como armazenado — nunca re-serializar o modelo em outro
ponto do código, ou uma mudança de serialização do Pydantic invalidaria toda
aprovação silenciosamente.
"""

from __future__ import annotations

import hashlib

from sqlmodel import Session, col, select

from src.api.models import AuditEntry, Draft, DraftRevision, utcnow
from src.schema.state import ApprovalStatus, PipelineState


class DraftAlreadySentError(RuntimeError):
    """Raised when an edit is attempted on a draft that was already sent."""


def state_sha256(state_json: str) -> str:
    """sha256 hex do snapshot armazenado (auditável, sem PII no log — só o hash)."""
    return hashlib.sha256(state_json.encode("utf-8")).hexdigest()


def _require(session: Session, draft_id: int) -> Draft:
    draft = session.get(Draft, draft_id)
    if draft is None:
        raise KeyError(f"Draft {draft_id} not found")
    return draft


def add_audit(
    session: Session, draft_id: int, actor: str, action: str, detail: str | None = None
) -> AuditEntry:
    entry = _stage_audit(session, draft_id, actor, action, detail)
    session.commit()
    session.refresh(entry)
    return entry


def _stage_audit(
    session: Session, draft_id: int, actor: str, action: str, detail: str | None = None
) -> AuditEntry:
    """Attach an audit entry without committing, for atomic repository operations."""
    entry = AuditEntry(draft_id=draft_id, actor=actor, action=action, detail=detail)
    session.add(entry)
    return entry


def _stage_revision(session: Session, draft: Draft) -> DraftRevision:
    """Attach the current immutable snapshot without committing it separately."""
    assert draft.id is not None
    revision = DraftRevision(
        draft_id=draft.id,
        revision=draft.revision,
        state_sha256=state_sha256(draft.state_json),
        state_json=draft.state_json,
    )
    session.add(revision)
    return revision


def create_draft(session: Session, state: PipelineState, actor: str = "system") -> Draft:
    """Persist a new pending draft from a PipelineState and audit the submission."""
    draft = Draft(status=ApprovalStatus.PENDING, state_json=state.model_dump_json())
    try:
        session.add(draft)
        session.flush()  # assigns the PK without ending the transaction
        assert draft.id is not None
        _stage_revision(session, draft)
        _stage_audit(session, draft.id, actor=actor, action="submitted")
        session.commit()
    except Exception:
        session.rollback()
        raise
    session.refresh(draft)
    return draft


def get_draft(session: Session, draft_id: int) -> Draft | None:
    return session.get(Draft, draft_id)


def list_drafts(session: Session) -> list[Draft]:
    return list(session.exec(select(Draft).order_by(col(Draft.created_at))))


def set_status(session: Session, draft_id: int, status: ApprovalStatus, actor: str) -> Draft:
    """Update a draft's status and write an audit row.

    APPROVED estampa a revisão + hash do conteúdo aprovado (o gate de envio exige
    que ambos ainda batam); qualquer outro status limpa o stamp.
    """
    draft = _require(session, draft_id)
    if draft.sent_at is not None:
        add_audit(
            session,
            draft_id,
            actor=actor,
            action="status_blocked",
            detail="already_sent",
        )
        raise DraftAlreadySentError(
            f"Draft {draft_id} was already sent — status change blocked."
        )
    try:
        draft.status = status
        if status == ApprovalStatus.APPROVED:
            draft.approved_revision = draft.revision
            draft.approved_state_sha256 = state_sha256(draft.state_json)
            detail = f"rev={draft.revision} sha256={draft.approved_state_sha256[:12]}"
        else:
            draft.approved_revision = None
            draft.approved_state_sha256 = None
            detail = None
        draft.updated_at = utcnow()
        session.add(draft)
        _stage_audit(
            session,
            draft_id,
            actor=actor,
            action=f"status:{status}",
            detail=detail,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    session.refresh(draft)
    return draft


def mark_sent(session: Session, draft_id: int, actor: str) -> Draft:
    """Record that a draft was sent (sets sent_at + audit). The gate enforces policy."""
    draft = _require(session, draft_id)
    try:
        now = utcnow()
        draft.sent_at = now
        draft.updated_at = now
        session.add(draft)
        _stage_audit(session, draft_id, actor=actor, action="sent")
        session.commit()
    except Exception:
        session.rollback()
        raise
    session.refresh(draft)
    return draft


def update_state(
    session: Session, draft_id: int, state: PipelineState, actor: str, action: str = "edited"
) -> Draft:
    """Replace a draft's stored PipelineState (e.g. after human edits) + audit.

    O guard fica AQUI (função compartilhada) para proteger todos os callers:
    - draft enviado é imutável (o registro do que foi enviado não pode mudar);
    - toda edição incrementa `revision`;
    - editar um draft aprovado revoga a aprovação (volta a PENDING) — o conteúdo
      novo precisa ser reaprovado por um humano antes de qualquer envio.
    """
    draft = _require(session, draft_id)
    if draft.sent_at is not None:
        add_audit(session, draft_id, actor=actor, action="edit_blocked", detail="already_sent")
        raise DraftAlreadySentError(f"Draft {draft_id} was already sent — edit blocked.")

    try:
        draft.state_json = state.model_dump_json()
        draft.revision += 1
        if draft.status == ApprovalStatus.APPROVED:
            draft.status = ApprovalStatus.PENDING
            draft.approved_revision = None
            draft.approved_state_sha256 = None
            _stage_audit(
                session,
                draft_id,
                actor=actor,
                action="approval_revoked",
                detail=f"rev={draft.revision}",
            )
        draft.updated_at = utcnow()
        session.add(draft)
        _stage_revision(session, draft)
        _stage_audit(
            session,
            draft_id,
            actor=actor,
            action=action,
            detail=(
                f"rev={draft.revision} sha256={state_sha256(draft.state_json)[:12]}"
            ),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    session.refresh(draft)
    return draft


def get_audit(session: Session, draft_id: int) -> list[AuditEntry]:
    return list(
        session.exec(
            select(AuditEntry)
            .where(col(AuditEntry.draft_id) == draft_id)
            .order_by(col(AuditEntry.id))
        )
    )
