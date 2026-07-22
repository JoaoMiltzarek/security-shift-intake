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
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import and_, or_
from sqlalchemy import select as sa_select
from sqlmodel import Session, col, select

from src.api.models import AuditEntry, DeliveryMode, Draft, DraftRevision, utcnow
from src.schema.state import ApprovalStatus, PipelineState


class DraftAlreadySentError(RuntimeError):
    """Raised when an edit is attempted on a draft that was already sent."""


class DraftOperationConflictError(RuntimeError):
    """Raised when another operation owns the draft's irreversible transition."""


_DRAFT_LOCKS_GUARD = threading.Lock()


@dataclass(slots=True)
class _DraftLockEntry:
    lock: threading.Lock = field(default_factory=threading.Lock)
    references: int = 0


_DRAFT_LOCKS: dict[tuple[int, int], _DraftLockEntry] = {}


@dataclass(frozen=True, slots=True)
class DraftPageCursor:
    """Stable keyset cursor for the newest-first review queue."""

    created_at: datetime
    draft_id: int


@dataclass(frozen=True, slots=True)
class DraftSummary:
    """Queue projection deliberately excluding the PII-heavy ``state_json``."""

    id: int
    status: str
    revision: int
    approved_revision: int | None
    created_at: datetime
    updated_at: datetime
    delivery_mode: str | None
    sent_at: datetime | None


@dataclass(frozen=True, slots=True)
class DraftPage:
    items: list[DraftSummary]
    next_cursor: DraftPageCursor | None


@dataclass(frozen=True, slots=True)
class AuditPage:
    items: list[AuditEntry]
    next_before_id: int | None


DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
QUEUE_STATUSES = frozenset({"pending", "approved", "rejected", "simulated"})


@contextmanager
def draft_operation_lock(session: Session, draft_id: int, *, wait: bool) -> Iterator[None]:
    """Serialize one draft and release its lock entry after the final caller."""
    key = (id(session.get_bind()), draft_id)
    with _DRAFT_LOCKS_GUARD:
        entry = _DRAFT_LOCKS.setdefault(key, _DraftLockEntry())
        entry.references += 1
    acquired = False
    try:
        acquired = entry.lock.acquire(blocking=wait)
        if not acquired:
            raise DraftOperationConflictError(
                f"Draft {draft_id} has another operation in progress — retry safely."
            )
        yield
    finally:
        if acquired:
            entry.lock.release()
        with _DRAFT_LOCKS_GUARD:
            entry.references -= 1
            if entry.references == 0:
                _DRAFT_LOCKS.pop(key, None)


def state_sha256(state_json: str) -> str:
    """sha256 hex do snapshot armazenado (auditável, sem PII no log — só o hash)."""
    return hashlib.sha256(state_json.encode("utf-8")).hexdigest()


def _require(session: Session, draft_id: int) -> Draft:
    draft = session.get(Draft, draft_id)
    if draft is None:
        raise KeyError(f"Draft {draft_id} not found")
    return draft


def add_audit(
    session: Session,
    draft_id: int,
    actor: str,
    action: str,
    detail: str | None = None,
    *,
    revision: int | None = None,
    snapshot_sha256: str | None = None,
) -> AuditEntry:
    entry = _stage_audit(
        session,
        draft_id,
        actor,
        action,
        detail,
        revision=revision,
        snapshot_sha256=snapshot_sha256,
    )
    session.commit()
    session.refresh(entry)
    return entry


def _stage_audit(
    session: Session,
    draft_id: int,
    actor: str,
    action: str,
    detail: str | None = None,
    *,
    revision: int | None = None,
    snapshot_sha256: str | None = None,
) -> AuditEntry:
    """Attach an audit entry without committing, for atomic repository operations."""
    entry = AuditEntry(
        draft_id=draft_id,
        actor=actor,
        action=action,
        detail=detail,
        revision=revision,
        state_sha256=snapshot_sha256,
    )
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


def _ensure_revision_snapshot(session: Session, draft: Draft) -> DraftRevision:
    """Create a legacy snapshot once, or verify the existing revision is identical."""
    assert draft.id is not None
    existing = session.exec(
        select(DraftRevision).where(
            DraftRevision.draft_id == draft.id,
            DraftRevision.revision == draft.revision,
        )
    ).first()
    digest = state_sha256(draft.state_json)
    if existing is None:
        return _stage_revision(session, draft)
    if existing.state_sha256 != digest or existing.state_json != draft.state_json:
        raise DraftOperationConflictError(
            f"Draft {draft.id} revision {draft.revision} conflicts with its preserved snapshot."
        )
    return existing


def create_draft(session: Session, state: PipelineState, actor: str = "system") -> Draft:
    """Persist a new pending draft from a PipelineState and audit the submission."""
    draft = Draft(status=ApprovalStatus.PENDING, state_json=state.model_dump_json())
    try:
        session.add(draft)
        session.flush()  # assigns the PK without ending the transaction
        assert draft.id is not None
        _stage_revision(session, draft)
        _stage_audit(
            session,
            draft.id,
            actor=actor,
            action="submitted",
            revision=draft.revision,
            snapshot_sha256=state_sha256(draft.state_json),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    session.refresh(draft)
    return draft


def get_draft(session: Session, draft_id: int) -> Draft | None:
    return session.get(Draft, draft_id)


def list_drafts(session: Session) -> list[Draft]:
    """Compatibility read for callers that need complete states.

    Review queues should use :func:`list_draft_page`, which never selects
    ``state_json`` and remains bounded.
    """
    return list(session.exec(select(Draft).order_by(col(Draft.created_at))))


def _page_size(limit: int) -> int:
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
    return limit


def list_draft_page(
    session: Session,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: DraftPageCursor | None = None,
    status: ApprovalStatus | str | None = None,
) -> DraftPage:
    """Return a bounded newest-first queue page without loading document state."""
    page_size = _page_size(limit)
    status_value = str(status) if status is not None else None
    if status_value is not None and status_value not in QUEUE_STATUSES:
        raise ValueError("status must be pending, approved, rejected, or simulated")
    statement = sa_select(
        col(Draft.id),
        col(Draft.status),
        col(Draft.revision),
        col(Draft.approved_revision),
        col(Draft.created_at),
        col(Draft.updated_at),
        col(Draft.delivery_mode),
        col(Draft.sent_at),
    )
    if status_value == "simulated":
        statement = statement.where(col(Draft.sent_at).is_not(None))
    elif status_value is not None:
        statement = statement.where(col(Draft.status) == status_value)
        if status_value == "approved":
            statement = statement.where(col(Draft.sent_at).is_(None))
    if cursor is not None:
        statement = statement.where(
            or_(
                col(Draft.created_at) < cursor.created_at,
                and_(
                    col(Draft.created_at) == cursor.created_at,
                    col(Draft.id) < cursor.draft_id,
                ),
            )
        )
    statement = statement.order_by(
        col(Draft.created_at).desc(),
        col(Draft.id).desc(),
    ).limit(page_size + 1)
    rows = list(session.execute(statement))
    has_more = len(rows) > page_size
    rows = rows[:page_size]
    items = [
        DraftSummary(
            id=row[0],
            status=row[1],
            revision=row[2],
            approved_revision=row[3],
            created_at=row[4],
            updated_at=row[5],
            delivery_mode=row[6],
            sent_at=row[7],
        )
        for row in rows
    ]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = DraftPageCursor(created_at=last.created_at, draft_id=last.id)
    return DraftPage(items=items, next_cursor=next_cursor)


def set_status(
    session: Session,
    draft_id: int,
    status: ApprovalStatus,
    actor: str,
    *,
    expected_revision: int | None = None,
) -> Draft:
    with draft_operation_lock(session, draft_id, wait=False):
        session.expire_all()
        return _set_status_locked(
            session,
            draft_id,
            status,
            actor,
            expected_revision=expected_revision,
        )


def _set_status_locked(
    session: Session,
    draft_id: int,
    status: ApprovalStatus,
    actor: str,
    *,
    expected_revision: int | None,
) -> Draft:
    """Update a draft's status and write an audit row.

    APPROVED estampa a revisão + hash do conteúdo aprovado (o gate de envio exige
    que ambos ainda batam); qualquer outro status limpa o stamp.
    """
    draft = _require(session, draft_id)
    if expected_revision is not None and draft.revision != expected_revision:
        raise DraftOperationConflictError(
            f"Draft {draft_id} changed from revision {expected_revision} to "
            f"{draft.revision} — reload before changing status."
        )
    if draft.sent_at is not None:
        add_audit(
            session,
            draft_id,
            actor=actor,
            action="status_blocked",
            detail="already_sent",
        )
        raise DraftAlreadySentError(f"Draft {draft_id} was already sent — status change blocked.")
    try:
        draft.status = status
        if status == ApprovalStatus.APPROVED:
            _ensure_revision_snapshot(session, draft)
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
            revision=draft.revision,
            snapshot_sha256=state_sha256(draft.state_json),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    session.refresh(draft)
    return draft


def _mark_sent_locked(
    session: Session,
    draft_id: int,
    actor: str,
    delivery_mode: DeliveryMode,
) -> Draft:
    """Record a gate-authorized adapter attempt.

    This private transaction helper repeats the revision/hash checks so importing
    it directly cannot turn stale or unapproved content into a terminal record.
    Public callers must enter through ``gate.send_draft``.
    """
    draft = _require(session, draft_id)
    digest = state_sha256(draft.state_json)
    if draft.status != ApprovalStatus.APPROVED:
        raise DraftOperationConflictError(f"Draft {draft_id} is not approved.")
    if draft.approved_revision != draft.revision or draft.approved_state_sha256 != digest:
        raise DraftOperationConflictError(
            f"Draft {draft_id} approval does not match its current revision and content."
        )
    if draft.sent_at is not None:
        raise DraftAlreadySentError(f"Draft {draft_id} was already sent.")
    try:
        now = utcnow()
        draft.sent_at = now
        draft.delivery_mode = delivery_mode
        draft.updated_at = now
        session.add(draft)
        action = "send_simulated" if delivery_mode == "simulated" else "external_dispatch_completed"
        _stage_audit(
            session,
            draft_id,
            actor=actor,
            action=action,
            detail=(
                f"mode={delivery_mode} rev={draft.revision} "
                f"sha256={state_sha256(draft.state_json)[:12]}"
            ),
            revision=draft.revision,
            snapshot_sha256=digest,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    session.refresh(draft)
    return draft


def update_state(
    session: Session,
    draft_id: int,
    state: PipelineState,
    actor: str,
    action: str = "edited",
    *,
    expected_revision: int | None = None,
) -> Draft:
    with draft_operation_lock(session, draft_id, wait=False):
        session.expire_all()
        return _update_state_locked(
            session,
            draft_id,
            state,
            actor,
            action,
            expected_revision=expected_revision,
        )


def _update_state_locked(
    session: Session,
    draft_id: int,
    state: PipelineState,
    actor: str,
    action: str,
    *,
    expected_revision: int | None,
) -> Draft:
    """Replace a draft's stored PipelineState (e.g. after human edits) + audit.

    O guard fica AQUI (função compartilhada) para proteger todos os callers:
    - draft enviado é imutável (o registro do que foi enviado não pode mudar);
    - toda edição incrementa `revision`;
    - editar um draft aprovado revoga a aprovação (volta a PENDING) — o conteúdo
      novo precisa ser reaprovado por um humano antes de qualquer envio.
    """
    draft = _require(session, draft_id)
    if expected_revision is not None and draft.revision != expected_revision:
        raise DraftOperationConflictError(
            f"Draft {draft_id} changed from revision {expected_revision} to "
            f"{draft.revision} â€” reload before saving."
        )
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
                revision=draft.revision,
                snapshot_sha256=state_sha256(draft.state_json),
            )
        draft.updated_at = utcnow()
        session.add(draft)
        _stage_revision(session, draft)
        _stage_audit(
            session,
            draft_id,
            actor=actor,
            action=action,
            detail=(f"rev={draft.revision} sha256={state_sha256(draft.state_json)[:12]}"),
            revision=draft.revision,
            snapshot_sha256=state_sha256(draft.state_json),
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    session.refresh(draft)
    return draft


def get_audit_page(
    session: Session,
    draft_id: int,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    before_id: int | None = None,
) -> AuditPage:
    """Return one bounded audit page, newest page first and chronological within it."""
    page_size = _page_size(limit)
    statement = select(AuditEntry).where(col(AuditEntry.draft_id) == draft_id)
    if before_id is not None:
        if before_id < 1:
            raise ValueError("before_id must be a positive audit-entry id")
        statement = statement.where(col(AuditEntry.id) < before_id)
    statement = statement.order_by(col(AuditEntry.id).desc()).limit(page_size + 1)
    rows = list(session.exec(statement))
    has_more = len(rows) > page_size
    selected = rows[:page_size]
    next_before_id = selected[-1].id if has_more and selected else None
    selected.reverse()
    return AuditPage(items=selected, next_before_id=next_before_id)


def get_audit(
    session: Session,
    draft_id: int,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
) -> list[AuditEntry]:
    """Compatibility wrapper returning the latest bounded page chronologically."""
    return get_audit_page(session, draft_id, limit=limit).items
