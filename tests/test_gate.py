"""M7.b: the send gate enforces approval. The headline invariant test lives here."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlmodel import Session

from src.api.db import init_db, make_engine
from src.api.gate import DraftNotApprovedError, MockSender, Sender, send_draft
from src.api.repository import create_draft, get_audit, set_status
from src.schema.state import ApprovalStatus, PipelineState


@pytest.fixture
def session() -> Iterator[Session]:
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as s:
        yield s


def _state() -> PipelineState:
    return PipelineState(
        source_pdf=Path("r.pdf"),
        recipients=["tech_security", "general_support"],
        email_draft="Subject: ...\n\nbody",
    )


def test_mock_sender_satisfies_protocol() -> None:
    assert isinstance(MockSender(), Sender)


def test_approved_draft_sends_and_audits(session: Session) -> None:
    draft = create_draft(session, _state())
    assert draft.id is not None
    set_status(session, draft.id, ApprovalStatus.APPROVED, actor="r")

    sender = MockSender()
    send_draft(session, draft.id, sender, actor="r")

    assert sender.call_count == 1
    assert sender.sent[0][0] == ["tech_security", "general_support"]
    assert "sent" in [a.action for a in get_audit(session, draft.id)]


# --- The invariant: an unapproved draft CANNOT be sent ---


def test_pending_draft_cannot_be_sent(session: Session) -> None:
    draft = create_draft(session, _state())  # status: pending
    assert draft.id is not None
    sender = MockSender()

    with pytest.raises(DraftNotApprovedError):
        send_draft(session, draft.id, sender, actor="r")

    # The side effect must NOT have happened.
    assert sender.call_count == 0
    # The blocked attempt is audited.
    assert "send_blocked" in [a.action for a in get_audit(session, draft.id)]


def test_rejected_draft_cannot_be_sent(session: Session) -> None:
    draft = create_draft(session, _state())
    assert draft.id is not None
    set_status(session, draft.id, ApprovalStatus.REJECTED, actor="r")
    sender = MockSender()

    with pytest.raises(DraftNotApprovedError):
        send_draft(session, draft.id, sender, actor="r")
    assert sender.call_count == 0


def test_already_sent_draft_cannot_be_resent(session: Session) -> None:
    draft = create_draft(session, _state())
    assert draft.id is not None
    set_status(session, draft.id, ApprovalStatus.APPROVED, actor="r")
    sender = MockSender()
    send_draft(session, draft.id, sender, actor="r")  # first send ok

    with pytest.raises(DraftNotApprovedError):
        send_draft(session, draft.id, sender, actor="r")  # second blocked
    assert sender.call_count == 1  # not called again


def test_send_missing_draft_raises(session: Session) -> None:
    with pytest.raises(KeyError):
        send_draft(session, 999, MockSender(), actor="r")
