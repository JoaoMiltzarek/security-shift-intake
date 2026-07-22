"""SQLite connection policy and deterministic schema migration contracts."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from src.api.db import SCHEMA_VERSION, SQLITE_BUSY_TIMEOUT_MS, init_db, make_engine
from src.api.models import AuditEntry


def test_sqlite_connections_enforce_foreign_keys_and_busy_timeout() -> None:
    engine = make_engine("sqlite://")
    init_db(engine)

    with Session(engine) as session:
        connection = session.connection()
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert (
            connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == SQLITE_BUSY_TIMEOUT_MS
        )

        session.add(AuditEntry(draft_id=999, actor="test", action="orphan"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_file_database_uses_wal_and_records_ordered_migrations(tmp_path: Path) -> None:
    database = tmp_path / "policy.db"
    engine = make_engine(f"sqlite:///{database.as_posix()}", allow_test_path=True)

    init_db(engine)
    init_db(engine)

    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"
        migrations = list(
            connection.exec_driver_sql(
                "SELECT version, name FROM schema_migration ORDER BY version"
            )
        )
        assert [row[0] for row in migrations] == list(range(1, SCHEMA_VERSION + 1))
        assert len({row[1] for row in migrations}) == SCHEMA_VERSION
        indexes = {
            row[1]
            for row in connection.exec_driver_sql(
                "SELECT type, name FROM sqlite_master WHERE type = 'index'"
            )
        }
        assert "ix_draft_queue_status_created_id" in indexes
        assert "ix_auditentry_draft_id_id" in indexes

    engine.dispose()
