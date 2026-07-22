"""SQLite engine setup and ordered schema migrations for the local review store."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

# Importing models registers the tables on SQLModel.metadata before create_all.
from src.api import models  # noqa: F401  (side-effect import)
from src.paths import PRIVATE_ROOT, resolve_private_path

# Drafts contain PII, so the production database lives in the gitignored
# ``private/`` tree. Tests must explicitly opt in to another filesystem path.
DEFAULT_DB_URL = f"sqlite:///{(PRIVATE_ROOT / 'app.db').as_posix()}"
SQLITE_BUSY_TIMEOUT_MS = 5_000
_IN_MEMORY_URLS = {"sqlite://", "sqlite:///:memory:"}


def _prepare_sqlite_url(url: str, *, allow_test_path: bool) -> str:
    """Validate the backend and path before creating a directory or connection."""
    parsed = make_url(url)
    if parsed.drivername != "sqlite":
        raise ValueError("The v1 local store supports SQLite only.")
    if parsed.query:
        raise ValueError("SQLite URL query parameters are not supported by the v1 store.")
    if url in _IN_MEMORY_URLS:
        return url
    if not parsed.database:
        raise ValueError("A file-backed SQLite URL must name a database file.")

    path = Path(parsed.database)
    if allow_test_path:
        resolved = path.expanduser().resolve(strict=False)
    else:
        resolved = resolve_private_path(path, create_root=True)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return str(parsed.set(database=resolved.as_posix()))


def _install_sqlite_pragmas(engine: Engine, *, file_backed: bool) -> None:
    """Apply the safety/concurrency policy to every pooled SQLite connection."""

    @event.listens_for(engine, "connect")
    def configure_connection(
        dbapi_connection: sqlite3.Connection,
        _connection_record: object,
    ) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
            if file_backed:
                cursor.execute("PRAGMA journal_mode=WAL")
        finally:
            cursor.close()


def make_engine(url: str | None = None, *, allow_test_path: bool = False) -> Engine:
    """Create a SQLite engine with the local store's connection policy.

    ``check_same_thread=False`` lets FastAPI use the engine across worker threads.
    In-memory tests use one shared connection through ``StaticPool``.
    """
    requested_url = url or os.environ.get("INTAKE_DB_URL", DEFAULT_DB_URL)
    prepared_url = _prepare_sqlite_url(requested_url, allow_test_path=allow_test_path)
    connect_args = {"check_same_thread": False}
    is_memory = prepared_url in _IN_MEMORY_URLS
    if is_memory:
        engine = create_engine(
            prepared_url,
            echo=False,
            connect_args=connect_args,
            poolclass=StaticPool,
        )
    else:
        engine = create_engine(prepared_url, echo=False, connect_args=connect_args)
    _install_sqlite_pragmas(engine, file_backed=not is_memory)
    return engine


@dataclass(frozen=True)
class _Migration:
    version: int
    name: str
    apply: Callable[[Connection], None]


_DRAFT_REVISION_COLUMNS = {
    "revision": "INTEGER NOT NULL DEFAULT 1",
    "approved_revision": "INTEGER",
    "approved_state_sha256": "VARCHAR",
    "delivery_mode": "VARCHAR",
}

_AUDIT_SNAPSHOT_COLUMNS = {
    "revision": "INTEGER",
    "state_sha256": "VARCHAR(64)",
}


def _table_columns(connection: Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")}


def _add_columns(
    connection: Connection,
    *,
    table: str,
    columns: dict[str, str],
) -> None:
    existing = _table_columns(connection, table)
    for column, ddl in columns.items():
        if column not in existing:
            connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _migrate_revision_bound_approval(connection: Connection) -> None:
    _add_columns(
        connection,
        table="draft",
        columns=_DRAFT_REVISION_COLUMNS,
    )


def _migrate_audit_snapshot_references(connection: Connection) -> None:
    _add_columns(
        connection,
        table="auditentry",
        columns=_AUDIT_SNAPSHOT_COLUMNS,
    )


def _migrate_revision_identity(connection: Connection) -> None:
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "ux_draftrevision_draft_id_revision "
        "ON draftrevision (draft_id, revision)"
    )


def _migrate_repository_query_indexes(connection: Connection) -> None:
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_draft_queue_status_created_id "
        "ON draft (status, created_at DESC, id DESC)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_auditentry_draft_id_id ON auditentry (draft_id, id DESC)"
    )


_MIGRATIONS = (
    _Migration(1, "revision_bound_approval", _migrate_revision_bound_approval),
    _Migration(2, "audit_snapshot_references", _migrate_audit_snapshot_references),
    _Migration(3, "revision_identity", _migrate_revision_identity),
    _Migration(4, "repository_query_indexes", _migrate_repository_query_indexes),
)
SCHEMA_VERSION = _MIGRATIONS[-1].version


def _apply_migrations(engine: Engine) -> None:
    """Apply each schema change once, in order, inside one transaction."""
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS schema_migration ("
            "version INTEGER PRIMARY KEY, "
            "name VARCHAR NOT NULL, "
            "applied_at VARCHAR NOT NULL"
            ")"
        )
        rows = connection.exec_driver_sql(
            "SELECT version, name FROM schema_migration ORDER BY version"
        )
        applied = {int(row[0]): str(row[1]) for row in rows}
        unknown_versions = set(applied).difference(migration.version for migration in _MIGRATIONS)
        if unknown_versions:
            versions = ", ".join(str(version) for version in sorted(unknown_versions))
            raise RuntimeError(
                f"Database schema is newer than this build: migration(s) {versions}."
            )

        for migration in _MIGRATIONS:
            applied_name = applied.get(migration.version)
            if applied_name is not None:
                if applied_name != migration.name:
                    raise RuntimeError(
                        f"Migration {migration.version} is recorded as {applied_name!r}, "
                        f"expected {migration.name!r}."
                    )
                continue
            migration.apply(connection)
            connection.exec_driver_sql(
                "INSERT INTO schema_migration (version, name, applied_at) "
                "VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
                (migration.version, migration.name),
            )


def init_db(engine: Engine) -> None:
    """Create current tables, then upgrade legacy databases deterministically."""
    SQLModel.metadata.create_all(engine)
    _apply_migrations(engine)
