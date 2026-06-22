"""The human-approval send gate — the project's #1 safety invariant.

A draft can be sent ONLY from status `approved`. Any other status (or an
already-sent draft) is a hard block: the sender is never called and the attempt is
audited. Sending goes through a mockable `Sender` so tests can prove the side
effect did or did not happen.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from sqlmodel import Session

from src.api.models import Draft
from src.api.repository import add_audit, get_draft, mark_sent
from src.schema.state import ApprovalStatus, PipelineState


class DraftNotApprovedError(RuntimeError):
    """Raised when a send is attempted on a draft that is not approved."""


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

    state = PipelineState.model_validate_json(draft.state_json)
    sender.send(state.recipients, state.email_draft or "")
    return mark_sent(session, draft_id, actor=actor)
