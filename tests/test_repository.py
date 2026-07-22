"""M7.a: persistence + repository round-trips on an in-memory SQLite engine."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlmodel import Session

from src.api.db import init_db, make_engine
from src.api.gate import MemorySimulationRecorder, simulate_draft
from src.api.models import Draft
from src.api.repository import (
    DraftAlreadySimulatedError,
    DraftOperationConflictError,
    add_audit,
    create_draft,
    get_audit,
    get_audit_page,
    get_draft,
    list_draft_page,
    list_drafts,
    set_status,
)
from src.schema.extraction import NormalizedIncidentModel
from src.schema.state import ApprovalStatus, PipelineState


@pytest.fixture
def session() -> Iterator[Session]:
    engine = make_engine("sqlite://")  # in-memory
    init_db(engine)
    with Session(engine) as s:
        yield s


def _state() -> PipelineState:
    return PipelineState(
        source_pdf=Path("report.pdf"),
        transcription="hello",
        normalized=NormalizedIncidentModel(disposition="none"),
    )


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


def test_simulation_persists_terminal_mode_and_audit(session: Session) -> None:
    draft = create_draft(session, _state())
    assert draft.id is not None
    set_status(session, draft.id, ApprovalStatus.APPROVED, actor="r")
    simulate_draft(session, draft.id, MemorySimulationRecorder(), actor="r")

    refreshed = get_draft(session, draft.id)
    assert refreshed is not None and refreshed.sent_at is not None
    assert refreshed.delivery_mode == "simulated"
    audit = get_audit(session, draft.id)
    assert "simulation_completed" in [a.action for a in audit]
    assert audit[-1].detail is not None
    assert "mode=simulated rev=1 sha256=" in audit[-1].detail


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
        session,
        draft.id,
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
        for r in session.exec(select(DraftRevision).where(DraftRevision.draft_id == draft.id))
    }
    assert approved.approved_state_sha256 in hashes  # aprovação sempre prova o conteúdo


# --- F3.B1 (SSI-1006): revisão do draft + migração de DB legado ---


def test_database_rejects_duplicate_revision_numbers(session: Session) -> None:
    from sqlalchemy.exc import IntegrityError
    from sqlmodel import select

    from src.api.models import DraftRevision

    draft = create_draft(session, _state())
    assert draft.id is not None
    original = session.exec(
        select(DraftRevision).where(
            DraftRevision.draft_id == draft.id,
            DraftRevision.revision == 1,
        )
    ).one()
    session.add(
        DraftRevision(
            draft_id=draft.id,
            revision=1,
            state_sha256=original.state_sha256,
            state_json=original.state_json,
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


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


def test_stale_editor_cannot_overwrite_a_newer_revision(tmp_path: Path) -> None:
    from sqlmodel import select

    from src.api.models import DraftRevision
    from src.api.repository import update_state

    engine = make_engine(
        f"sqlite:///{(tmp_path / 'stale-editor.db').as_posix()}", allow_test_path=True
    )
    init_db(engine)
    with Session(engine) as setup:
        draft = create_draft(setup, _state())
        assert draft.id is not None
        draft_id = draft.id

    with Session(engine) as first, Session(engine) as stale:
        assert first.get(Draft, draft_id) is not None
        assert stale.get(Draft, draft_id) is not None
        update_state(
            first,
            draft_id,
            PipelineState(source_pdf=Path("report.pdf"), transcription="first edit"),
            actor="first",
            expected_revision=1,
        )
        with pytest.raises(DraftOperationConflictError, match="reload"):
            update_state(
                stale,
                draft_id,
                PipelineState(source_pdf=Path("report.pdf"), transcription="stale edit"),
                actor="stale",
                expected_revision=1,
            )

    with Session(engine) as verify:
        persisted = verify.get(Draft, draft_id)
        assert persisted is not None
        assert persisted.revision == 2
        assert PipelineState.model_validate_json(persisted.state_json).transcription == "first edit"
        revisions = list(
            verify.exec(select(DraftRevision).where(DraftRevision.draft_id == draft_id))
        )
        assert [revision.revision for revision in revisions] == [1, 2]


def test_approve_stamps_revision_and_hash(session: Session) -> None:
    from src.api.repository import state_sha256

    draft = create_draft(session, _state())
    assert draft.id is not None
    approved = set_status(session, draft.id, ApprovalStatus.APPROVED, actor="reviewer")

    assert approved.approved_revision == approved.revision == 1
    assert approved.approved_state_sha256 == state_sha256(approved.state_json)


def test_approval_and_send_audit_reference_the_full_snapshot(session: Session) -> None:
    from src.api.repository import state_sha256

    draft = create_draft(session, _state())
    assert draft.id is not None
    set_status(session, draft.id, ApprovalStatus.APPROVED, actor="reviewer")
    simulate_draft(session, draft.id, MemorySimulationRecorder(), actor="reviewer")

    expected_hash = state_sha256(draft.state_json)
    entries = {
        entry.action: entry
        for entry in get_audit(session, draft.id)
        if entry.action in {"status:approved", "simulation_completed"}
    }
    assert set(entries) == {"status:approved", "simulation_completed"}
    assert all(entry.revision == 1 for entry in entries.values())
    assert all(entry.state_sha256 == expected_hash for entry in entries.values())


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
    from src.api.repository import update_state

    draft = create_draft(session, _state())
    assert draft.id is not None
    set_status(session, draft.id, ApprovalStatus.APPROVED, actor="r")
    simulate_draft(session, draft.id, MemorySimulationRecorder(), actor="r")

    with pytest.raises(DraftAlreadySimulatedError):
        update_state(session, draft.id, _state(), actor="reviewer")

    refreshed = get_draft(session, draft.id)
    assert refreshed is not None
    assert PipelineState.model_validate_json(refreshed.state_json).transcription == "hello"
    assert "edit_blocked" in [a.action for a in get_audit(session, draft.id)]


@pytest.mark.parametrize("status", [ApprovalStatus.APPROVED, ApprovalStatus.REJECTED])
def test_sent_draft_rejects_later_status_changes(session: Session, status: ApprovalStatus) -> None:
    draft = create_draft(session, _state())
    assert draft.id is not None
    set_status(session, draft.id, ApprovalStatus.APPROVED, actor="r")
    simulate_draft(session, draft.id, MemorySimulationRecorder(), actor="r")

    with pytest.raises(DraftAlreadySimulatedError):
        set_status(session, draft.id, status, actor="r")

    refreshed = get_draft(session, draft.id)
    assert refreshed is not None
    assert refreshed.status == ApprovalStatus.APPROVED
    assert refreshed.sent_at is not None
    assert get_audit(session, draft.id)[-1].action == "status_blocked"


# --- SSI-1015: mutation + snapshot + audit are one transaction -----------------


def _fail_audit_action(monkeypatch: pytest.MonkeyPatch, action_to_fail: str) -> None:
    import src.api.repository as repository

    original = repository._stage_audit

    def fail_selected(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        action = kwargs.get("action") if "action" in kwargs else args[3]
        if action == action_to_fail:
            raise RuntimeError("injected audit staging failure")
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(repository, "_stage_audit", fail_selected)


def test_create_rolls_back_when_submission_audit_fails(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fail_audit_action(monkeypatch, "submitted")

    with pytest.raises(RuntimeError, match="injected audit"):
        create_draft(session, _state())

    session.expire_all()
    assert list_drafts(session) == []


def test_status_rolls_back_when_status_audit_fails(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = create_draft(session, _state())
    assert draft.id is not None
    _fail_audit_action(monkeypatch, "status:approved")

    with pytest.raises(RuntimeError, match="injected audit"):
        set_status(session, draft.id, ApprovalStatus.APPROVED, actor="r")

    session.expire_all()
    refreshed = get_draft(session, draft.id)
    assert refreshed is not None
    assert refreshed.status == ApprovalStatus.PENDING
    assert "status:approved" not in [entry.action for entry in get_audit(session, draft.id)]


def test_simulation_rolls_back_when_audit_fails(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = create_draft(session, _state())
    assert draft.id is not None
    set_status(session, draft.id, ApprovalStatus.APPROVED, actor="r")
    _fail_audit_action(monkeypatch, "simulation_completed")

    with pytest.raises(RuntimeError, match="injected audit"):
        simulate_draft(session, draft.id, MemorySimulationRecorder(), actor="r")

    session.expire_all()
    refreshed = get_draft(session, draft.id)
    assert refreshed is not None
    assert refreshed.sent_at is None
    assert refreshed.delivery_mode is None
    assert "simulation_completed" not in [entry.action for entry in get_audit(session, draft.id)]


def test_update_rolls_back_when_edit_audit_fails(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.api.repository import update_state

    draft = create_draft(session, _state())
    assert draft.id is not None
    _fail_audit_action(monkeypatch, "edited")
    edited = PipelineState(source_pdf=Path("report.pdf"), transcription="changed")

    with pytest.raises(RuntimeError, match="injected audit"):
        update_state(session, draft.id, edited, actor="r")

    session.expire_all()
    refreshed = get_draft(session, draft.id)
    assert refreshed is not None
    assert refreshed.revision == 1
    assert PipelineState.model_validate_json(refreshed.state_json).transcription == "hello"


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

    engine = make_engine(f"sqlite:///{db.as_posix()}", allow_test_path=True)
    init_db(engine)  # deve migrar in-place, idempotente
    init_db(engine)  # segunda chamada não pode falhar nem duplicar colunas

    with Session(engine) as s:
        from sqlmodel import select

        from src.api.models import DraftRevision

        draft = s.get(Draft, 1)
        assert draft is not None
        assert draft.status == "approved"
        assert draft.revision == 1
        assert draft.approved_revision is None
        assert draft.approved_state_sha256 is None
        assert draft.delivery_mode is None

        reapproved = set_status(s, 1, ApprovalStatus.APPROVED, actor="legacy-reviewer")
        snapshots = list(s.exec(select(DraftRevision).where(DraftRevision.draft_id == 1)))
        assert len(snapshots) == 1
        assert snapshots[0].revision == reapproved.revision == 1
        assert snapshots[0].state_sha256 == reapproved.approved_state_sha256


def test_status_compare_and_swap_rejects_stale_revision(session: Session) -> None:
    from src.api.repository import update_state

    draft = create_draft(session, _state())
    assert draft.id is not None
    update_state(session, draft.id, _state(), actor="first", expected_revision=1)

    with pytest.raises(DraftOperationConflictError, match="reload"):
        set_status(
            session,
            draft.id,
            ApprovalStatus.APPROVED,
            actor="stale",
            expected_revision=1,
        )

    refreshed = get_draft(session, draft.id)
    assert refreshed is not None
    assert refreshed.status == ApprovalStatus.PENDING


def test_draft_lock_entries_are_reclaimed_after_success_and_conflict(session: Session) -> None:
    import src.api.repository as repository

    with repository.draft_operation_lock(session, 7, wait=False):
        assert len(repository._DRAFT_LOCKS) == 1
        with (
            pytest.raises(DraftOperationConflictError),
            repository.draft_operation_lock(session, 7, wait=False),
        ):
            pytest.fail("the nested operation must not acquire the same draft lock")
        assert len(repository._DRAFT_LOCKS) == 1
    assert repository._DRAFT_LOCKS == {}


def test_queue_page_is_keyset_paginated_without_selecting_state_json(session: Session) -> None:
    for _ in range(5):
        create_draft(session, _state())

    statements: list[str] = []
    engine = session.get_bind()

    def capture_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        first = list_draft_page(session, limit=2)
        assert first.next_cursor is not None
        second = list_draft_page(session, limit=2, cursor=first.next_cursor)
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)

    assert len(first.items) == len(second.items) == 2
    assert {item.id for item in first.items}.isdisjoint(item.id for item in second.items)
    assert [item.id for item in first.items] == sorted(
        (item.id for item in first.items), reverse=True
    )
    normalized_statements = [" ".join(sql.lower().split()) for sql in statements]
    draft_selects = [sql for sql in normalized_statements if " from draft" in sql]
    assert draft_selects
    assert all("state_json" not in sql for sql in draft_selects)


def test_queue_page_filters_status_and_bounds_limit(session: Session) -> None:
    pending = create_draft(session, _state())
    approved = create_draft(session, _state())
    assert approved.id is not None
    set_status(session, approved.id, ApprovalStatus.APPROVED, actor="r")

    page = list_draft_page(session, status=ApprovalStatus.PENDING)
    assert [item.id for item in page.items] == [pending.id]
    with pytest.raises(ValueError, match="limit"):
        list_draft_page(session, limit=101)
    with pytest.raises(ValueError, match="status"):
        list_draft_page(session, status="deleted")


def test_queue_page_separates_approved_from_simulated(session: Session) -> None:
    approved = create_draft(session, _state())
    simulated = create_draft(session, _state())
    assert approved.id is not None
    assert simulated.id is not None
    set_status(session, approved.id, ApprovalStatus.APPROVED, actor="reviewer")
    set_status(session, simulated.id, ApprovalStatus.APPROVED, actor="reviewer")
    simulate_draft(session, simulated.id, MemorySimulationRecorder(), actor="reviewer")

    approved_page = list_draft_page(session, status="approved")
    simulated_page = list_draft_page(session, status="simulated")

    assert [item.id for item in approved_page.items] == [approved.id]
    assert [item.id for item in simulated_page.items] == [simulated.id]


def test_audit_pages_are_bounded_complete_and_non_overlapping(session: Session) -> None:
    draft = create_draft(session, _state())
    assert draft.id is not None
    for index in range(6):
        add_audit(session, draft.id, actor="reviewer", action=f"note:{index}")

    first = get_audit_page(session, draft.id, limit=3)
    assert len(first.items) == 3
    assert first.next_before_id is not None
    second = get_audit_page(
        session,
        draft.id,
        limit=3,
        before_id=first.next_before_id,
    )

    assert len(second.items) == 3
    assert {entry.id for entry in first.items}.isdisjoint(entry.id for entry in second.items)
    assert [entry.id for entry in first.items] == sorted(
        entry.id for entry in first.items if entry.id is not None
    )
    with pytest.raises(ValueError, match="before_id"):
        get_audit_page(session, draft.id, before_id=0)


def test_terminal_state_can_only_be_recorded_through_gate(session: Session) -> None:
    import src.api.repository as repository

    draft = create_draft(session, _state())
    assert draft.id is not None
    assert not hasattr(repository, "mark_sent")
    with pytest.raises(DraftOperationConflictError, match="not approved"):
        repository._mark_simulated_locked(session, draft.id, "bypass")
