"""M7.a: persistence + repository round-trips on an in-memory SQLite engine."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlmodel import Session

from src.api.db import init_db, make_engine
from src.api.models import Draft
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


# --- F5 (SSI-1008): snapshot por revisão — provar o que foi aprovado/enviado ---


def test_every_revision_snapshot_is_preserved(session: Session) -> None:
    from sqlmodel import select

    from src.api.models import DraftRevision
    from src.api.repository import state_sha256, update_state

    draft = create_draft(session, _state())
    assert draft.id is not None
    update_state(
        session, draft.id,
        PipelineState(source_pdf=Path("report.pdf"), transcription="v2"),
        actor="reviewer",
    )

    revs = list(
        session.exec(
            select(DraftRevision)
            .where(DraftRevision.draft_id == draft.id)
            .order_by(DraftRevision.revision)  # type: ignore[arg-type]
        )
    )
    assert [r.revision for r in revs] == [1, 2]
    assert "hello" in revs[0].state_json  # a revisão substituída continua provável
    assert "v2" in revs[1].state_json
    current = get_draft(session, draft.id)
    assert current is not None
    assert revs[1].state_sha256 == state_sha256(current.state_json)


def test_approved_hash_matches_a_preserved_revision(session: Session) -> None:
    from sqlmodel import select

    from src.api.models import DraftRevision

    draft = create_draft(session, _state())
    assert draft.id is not None
    approved = set_status(session, draft.id, ApprovalStatus.APPROVED, actor="reviewer")

    hashes = {
        r.state_sha256
        for r in session.exec(
            select(DraftRevision).where(DraftRevision.draft_id == draft.id)
        )
    }
    assert approved.approved_state_sha256 in hashes  # aprovação sempre prova o conteúdo


# --- F3.B1 (SSI-1006): revisão do draft + migração de DB legado ---


def test_new_draft_starts_at_revision_1_without_approval_stamp(session: Session) -> None:
    draft = create_draft(session, _state())
    assert draft.revision == 1
    assert draft.approved_revision is None
    assert draft.approved_state_sha256 is None


def test_state_sha256_hashes_the_stored_string() -> None:
    import hashlib

    from src.api.repository import state_sha256

    payload = '{"source_pdf": "x.pdf"}'
    assert state_sha256(payload) == hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_update_state_bumps_revision_and_audits_hash(session: Session) -> None:
    from src.api.repository import state_sha256, update_state

    draft = create_draft(session, _state())
    assert draft.id is not None
    updated = update_state(session, draft.id, _state(), actor="reviewer")

    assert updated.revision == 2
    entry = get_audit(session, draft.id)[-1]
    assert entry.action == "edited"
    assert entry.detail is not None
    assert "rev=2" in entry.detail
    assert state_sha256(updated.state_json)[:12] in entry.detail


def test_approve_stamps_revision_and_hash(session: Session) -> None:
    from src.api.repository import state_sha256

    draft = create_draft(session, _state())
    assert draft.id is not None
    approved = set_status(session, draft.id, ApprovalStatus.APPROVED, actor="reviewer")

    assert approved.approved_revision == approved.revision == 1
    assert approved.approved_state_sha256 == state_sha256(approved.state_json)


def test_reject_clears_approval_stamp(session: Session) -> None:
    draft = create_draft(session, _state())
    assert draft.id is not None
    set_status(session, draft.id, ApprovalStatus.APPROVED, actor="r")
    rejected = set_status(session, draft.id, ApprovalStatus.REJECTED, actor="r")

    assert rejected.approved_revision is None
    assert rejected.approved_state_sha256 is None


def test_edit_approved_draft_revokes_approval(session: Session) -> None:
    from src.api.repository import update_state

    draft = create_draft(session, _state())
    assert draft.id is not None
    set_status(session, draft.id, ApprovalStatus.APPROVED, actor="r")
    updated = update_state(session, draft.id, _state(), actor="reviewer")

    assert updated.status == ApprovalStatus.PENDING  # aprovação não vale p/ conteúdo novo
    assert updated.approved_revision is None
    assert updated.approved_state_sha256 is None
    assert "approval_revoked" in [a.action for a in get_audit(session, draft.id)]


def test_edit_sent_draft_raises_and_audits(session: Session) -> None:
    from src.api.repository import DraftAlreadySentError, update_state

    draft = create_draft(session, _state())
    assert draft.id is not None
    set_status(session, draft.id, ApprovalStatus.APPROVED, actor="r")
    mark_sent(session, draft.id, actor="r")

    with pytest.raises(DraftAlreadySentError):
        update_state(session, draft.id, _state(), actor="reviewer")

    refreshed = get_draft(session, draft.id)
    assert refreshed is not None
    assert PipelineState.model_validate_json(refreshed.state_json).transcription == "hello"
    assert "edit_blocked" in [a.action for a in get_audit(session, draft.id)]


def test_init_db_migrates_legacy_draft_table(tmp_path: Path) -> None:
    """Um DB criado ANTES do vínculo aprovação↔revisão ganha as colunas novas sem
    perder linhas; o draft aprovado legado fica com approved_revision NULL (send
    bloqueado até reaprovação — o caminho seguro)."""
    import sqlite3

    db = tmp_path / "legacy.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE draft ("
        "id INTEGER PRIMARY KEY, status VARCHAR NOT NULL, state_json VARCHAR NOT NULL, "
        "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, sent_at DATETIME)"
    )
    con.execute(
        "INSERT INTO draft (status, state_json, created_at, updated_at) "
        "VALUES ('approved', '{\"source_pdf\": \"legacy.pdf\"}', "
        "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
    )
    con.commit()
    con.close()

    engine = make_engine(f"sqlite:///{db.as_posix()}")
    init_db(engine)  # deve migrar in-place, idempotente
    init_db(engine)  # segunda chamada não pode falhar nem duplicar colunas

    with Session(engine) as s:
        draft = s.get(Draft, 1)
        assert draft is not None
        assert draft.status == "approved"
        assert draft.revision == 1
        assert draft.approved_revision is None
        assert draft.approved_state_sha256 is None
