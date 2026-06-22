"""M7.a: persistence + repository round-trips on an in-memory SQLite engine."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlmodel import Session

from src.api.db import init_db, make_engine
from src.api.repository import (
    add_audit,
    create_draft,
    get_audit,
    get_draft,
    list_drafts,
    mark_sent,
    set_status,
)
from src.schema.state import ApprovalStatus, PipelineState


@pytest.fixture
def session() -> Iterator[Session]:
    engine = make_engine("sqlite://")  # in-memory
    init_db(engine)
    with Session(engine) as s:
        yield s


def _state() -> PipelineState:
    return PipelineState(source_pdf=Path("report.pdf"), transcription="hello")


def test_create_draft_is_pending_and_audited(session: Session) -> None:
    draft = create_draft(session, _state())
    assert draft.id is not None
    assert draft.status == ApprovalStatus.PENDING
    audit = get_audit(session, draft.id)
    assert [a.action for a in audit] == ["submitted"]


def test_state_json_round_trips(session: Session) -> None:
    draft = create_draft(session, _state())
    reloaded = PipelineState.model_validate_json(draft.state_json)
    assert reloaded.transcription == "hello"


def test_set_status_updates_and_audits(session: Session) -> None:
    draft = create_draft(session, _state())
    assert draft.id is not None
    set_status(session, draft.id, ApprovalStatus.APPROVED, actor="reviewer@x")

    refreshed = get_draft(session, draft.id)
    assert refreshed is not None
    assert refreshed.status == ApprovalStatus.APPROVED
    actions = [a.action for a in get_audit(session, draft.id)]
    assert "status:approved" in actions


def test_mark_sent_sets_timestamp_and_audit(session: Session) -> None:
    draft = create_draft(session, _state())
    assert draft.id is not None
    set_status(session, draft.id, ApprovalStatus.APPROVED, actor="r")
    mark_sent(session, draft.id, actor="r")

    refreshed = get_draft(session, draft.id)
    assert refreshed is not None and refreshed.sent_at is not None
    assert "sent" in [a.action for a in get_audit(session, draft.id)]


def test_list_drafts_returns_all(session: Session) -> None:
    create_draft(session, _state())
    create_draft(session, _state())
    assert len(list_drafts(session)) == 2


def test_get_missing_draft_returns_none(session: Session) -> None:
    assert get_draft(session, 999) is None


def test_set_status_missing_draft_raises(session: Session) -> None:
    with pytest.raises(KeyError):
        set_status(session, 999, ApprovalStatus.APPROVED, actor="r")


def test_audit_records_actor_and_detail(session: Session) -> None:
    draft = create_draft(session, _state())
    assert draft.id is not None
    add_audit(session, draft.id, actor="reviewer@x", action="note", detail="looks ok")
    entry = get_audit(session, draft.id)[-1]
    assert entry.actor == "reviewer@x"
    assert entry.detail == "looks ok"
