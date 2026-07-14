"""M7.b: the send gate enforces approval. The headline invariant test lives here."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlmodel import Session

from src.api.db import init_db, make_engine
from src.api.gate import DraftNotApprovedError, MockSender, Sender, send_draft
from src.api.models import DeliveryMode, Draft
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
    sender = MockSender()
    assert isinstance(sender, Sender)
    assert sender.delivery_mode == "simulated"


def test_approved_draft_sends_and_audits(session: Session) -> None:
    draft = create_draft(session, _state())
    assert draft.id is not None
    set_status(session, draft.id, ApprovalStatus.APPROVED, actor="r")

    sender = MockSender()
    send_draft(session, draft.id, sender, actor="r")

    assert sender.call_count == 1
    assert sender.sent[0][0] == ["tech_security", "general_support"]
    assert "send_simulated" in [a.action for a in get_audit(session, draft.id)]


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


# --- F3.B3 (SSI-1006): o envio é do CONTEÚDO aprovado, não só do status ---


def test_hash_tampered_state_cannot_be_sent(session: Session) -> None:
    """Escrita direta em state_json (fora de update_state) mantendo status approved:
    o hash estampado não bate → send bloqueia. Defesa em profundidade além do reset
    de status feito por update_state."""
    draft = create_draft(session, _state())
    assert draft.id is not None
    set_status(session, draft.id, ApprovalStatus.APPROVED, actor="r")

    tampered = _state().model_copy(update={"email_draft": "Subject: outro\n\ncorpo trocado"})
    draft.state_json = tampered.model_dump_json()  # bypass deliberado de update_state
    session.add(draft)
    session.commit()

    sender = MockSender()
    with pytest.raises(DraftNotApprovedError):
        send_draft(session, draft.id, sender, actor="r")
    assert sender.call_count == 0
    blocked = [a for a in get_audit(session, draft.id) if a.action == "send_blocked"]
    assert blocked and blocked[-1].detail is not None
    assert "stale_approval" in blocked[-1].detail


def test_legacy_approved_without_stamp_cannot_be_sent(session: Session) -> None:
    """Draft aprovado ANTES do vínculo por revisão (approved_revision NULL, como após a
    migração de DB legado) não pode ser enviado até reaprovação."""
    draft = create_draft(session, _state())
    assert draft.id is not None
    draft.status = ApprovalStatus.APPROVED  # aprovação legada: sem stamp
    session.add(draft)
    session.commit()

    sender = MockSender()
    with pytest.raises(DraftNotApprovedError):
        send_draft(session, draft.id, sender, actor="r")
    assert sender.call_count == 0


def test_send_reruns_assert_reviewable_on_current_state(session: Session) -> None:
    """Mesmo com status/revisão/hash válidos, um estado corrente com pendências de
    revisão nunca é enviado — send re-roda assert_reviewable."""
    pending_state = _state().model_copy(update={"must_review_fields": ["guard_name"]})
    draft = create_draft(session, pending_state)
    assert draft.id is not None
    set_status(session, draft.id, ApprovalStatus.APPROVED, actor="r")  # stamp válido

    sender = MockSender()
    with pytest.raises(DraftNotApprovedError):
        send_draft(session, draft.id, sender, actor="r")
    assert sender.call_count == 0


def test_concurrent_send_calls_invoke_sender_exactly_once(tmp_path: Path) -> None:
    engine = make_engine(
        f"sqlite:///{(tmp_path / 'send-race.db').as_posix()}", allow_test_path=True
    )
    init_db(engine)
    with Session(engine) as setup:
        draft = create_draft(setup, _state())
        assert draft.id is not None
        draft_id = draft.id
        set_status(setup, draft_id, ApprovalStatus.APPROVED, actor="r")

    class SlowSender:
        delivery_mode: DeliveryMode = "external"

        def __init__(self) -> None:
            self.call_count = 0
            self._guard = threading.Lock()

        def send(self, recipients: list[str], body: str) -> None:
            with self._guard:
                self.call_count += 1
            time.sleep(0.1)  # deixa a segunda sessão explorar a janela pré-sent_at

    sender = SlowSender()
    start = threading.Barrier(3)

    def attempt() -> str:
        with Session(engine) as concurrent_session:
            start.wait(timeout=5)
            try:
                send_draft(concurrent_session, draft_id, sender, actor="r")
                return "sent"
            except DraftNotApprovedError:
                return "blocked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        start.wait(timeout=5)
        outcomes = [future.result(timeout=10) for future in futures]

    assert sender.call_count == 1
    assert sorted(outcomes) == ["blocked", "sent"]
    with Session(engine) as verify:
        persisted = verify.get(Draft, draft_id)
        assert persisted is not None
        assert persisted.delivery_mode == "external"
        assert [entry.action for entry in get_audit(verify, draft_id)].count(
            "external_dispatch_completed"
        ) == 1
