"""The human-approval send gate — the project's #1 safety invariant.

A draft can be sent ONLY from status `approved`. Any other status (or an
already-sent draft) is a hard block: the sender is never called and the attempt is
audited. Sending goes through a mockable `Sender` so tests can prove the side
effect did or did not happen.
"""

from __future__ import annotations

import threading
from typing import Protocol, runtime_checkable

from sqlmodel import Session

from src.api.models import Draft
from src.api.repository import add_audit, get_draft, mark_sent, state_sha256
from src.pipeline.ocr_quality import OCR_FAILED
from src.schema.state import ApprovalStatus, PipelineState

_SEND_LOCKS_GUARD = threading.Lock()
_SEND_LOCKS: dict[int, threading.Lock] = {}


def _draft_send_lock(draft_id: int) -> threading.Lock:
    """Return the process-local lock for a draft (supported v1 is one Uvicorn process)."""
    with _SEND_LOCKS_GUARD:
        return _SEND_LOCKS.setdefault(draft_id, threading.Lock())


class DraftNotApprovedError(RuntimeError):
    """Raised when a send is attempted on a draft that is not approved."""


class DraftNotReviewableError(RuntimeError):
    """Raised when approval is attempted while fields still need review (plano R4)."""


def assert_reviewable(state: PipelineState) -> None:
    """Block approval while any field is still flagged for review (plano R4).

    Enforces "nunca adivinhar": a draft cannot be approved while the critic's
    `must_review_fields` is non-empty (low-confidence, missing, invalid, or ambiguous
    values). The human must resolve every flag (edit screen) before approving.

    Also a hard safety block when the OCR quality gate failed: a document the OCR
    could not read is never approvable until a human transcribes/corrects it (which
    clears the failed state). Explicit so the block does not rely on the critic
    coincidentally leaving fields pending.
    """
    if state.ocr_quality == OCR_FAILED:
        raise DraftNotReviewableError(
            "OCR quality failed — manual transcription required before approval."
        )
    if state.must_review_fields:
        raise DraftNotReviewableError(
            f"{len(state.must_review_fields)} field(s) need review before approval: "
            f"{', '.join(state.must_review_fields)}."
        )
    if state.normalized is not None and state.normalized.disposition == "unknown":
        raise DraftNotReviewableError(
            "Occurrence disposition is unknown — explicit human confirmation required."
        )


@runtime_checkable
class Sender(Protocol):
    """Performs the irreversible action. Implementations: MockSender (tests)."""

    def send(self, recipients: list[str], body: str) -> None: ...


class MockSender:
    """Records sends instead of performing them. MOCK — nothing is actually sent."""

    def __init__(self) -> None:
        self.sent: list[tuple[list[str], str]] = []

    @property
    def call_count(self) -> int:
        return len(self.sent)

    def send(self, recipients: list[str], body: str) -> None:
        self.sent.append((recipients, body))


def send_draft(
    session: Session, draft_id: int, sender: Sender, actor: str = "reviewer"
) -> Draft:
    """Serialize the irreversible side effect per draft in the supported local process."""
    with _draft_send_lock(draft_id):
        # A concurrent session may have committed sent_at while this caller waited.
        session.expire_all()
        return _send_draft_once(session, draft_id, sender, actor)


def _send_draft_once(
    session: Session, draft_id: int, sender: Sender, actor: str = "reviewer"
) -> Draft:
    """Send a draft iff it is approved. Otherwise block, audit, and raise.

    The sender is invoked only on the approved path — never for a blocked attempt.
    """
    draft = get_draft(session, draft_id)
    if draft is None:
        raise KeyError(f"Draft {draft_id} not found")

    if draft.status != ApprovalStatus.APPROVED:
        add_audit(
            session, draft_id, actor=actor, action="send_blocked",
            detail=f"status={draft.status}",
        )
        raise DraftNotApprovedError(
            f"Draft {draft_id} is '{draft.status}', not approved — send blocked."
        )

    if draft.sent_at is not None:
        add_audit(
            session, draft_id, actor=actor, action="send_blocked", detail="already_sent"
        )
        raise DraftNotApprovedError(f"Draft {draft_id} was already sent — send blocked.")

    # A aprovação vale para UMA revisão/conteúdo (SSI-1006): revisão e hash estampados
    # no approve precisam bater com o estado corrente. Cobre aprovação legada
    # (approved_revision NULL) e escrita direta em state_json fora de update_state.
    if (
        draft.approved_revision != draft.revision
        or draft.approved_state_sha256 != state_sha256(draft.state_json)
    ):
        add_audit(
            session, draft_id, actor=actor, action="send_blocked",
            detail=(
                f"stale_approval rev={draft.revision} "
                f"approved_rev={draft.approved_revision}"
            ),
        )
        raise DraftNotApprovedError(
            f"Draft {draft_id} content is not the approved revision — send blocked; "
            "re-approve the current content."
        )

    state = PipelineState.model_validate_json(draft.state_json)

    # Última linha de defesa: o estado corrente precisa continuar aprovável
    # (sem pendências, sem OCR falho, sem disposição unknown) no momento do envio.
    try:
        assert_reviewable(state)
    except DraftNotReviewableError as exc:
        add_audit(
            session, draft_id, actor=actor, action="send_blocked", detail="not_reviewable"
        )
        raise DraftNotApprovedError(str(exc)) from exc

    sender.send(state.recipients, state.email_draft or "")
    return mark_sent(session, draft_id, actor=actor)
