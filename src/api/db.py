"""Database engine and session helpers for the approval-gate API.

Importing this module registers the SQLModel tables (via `models`). Tests use an
in-memory SQLite engine; the app uses a file-backed one.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

# Importing models registers the tables on SQLModel.metadata before create_all.
from src.api import models  # noqa: F401  (side-effect import)
from src.paths import PRIVATE_ROOT, resolve_private_path

# Drafts contain PII (transcription/fields), so the DB lives in the gitignored
# `private/` folder by default. Override with INTAKE_DB_URL.
DEFAULT_DB_URL = f"sqlite:///{(PRIVATE_ROOT / 'app.db').as_posix()}"
_IN_MEMORY_URLS = {"sqlite://", "sqlite:///:memory:"}


def _prepare_sqlite_url(url: str, *, allow_test_path: bool) -> str:
    """Validate the backend/path before any directory or connection is created."""
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


def make_engine(url: str | None = None, *, allow_test_path: bool = False) -> Engine:
    """Create an engine. check_same_thread=False lets FastAPI use it across threads.

    For in-memory SQLite, use a StaticPool so every session shares the one
    connection (otherwise each session gets a fresh, empty database).
    """
    url = url or os.environ.get("INTAKE_DB_URL", DEFAULT_DB_URL)
    url = _prepare_sqlite_url(url, allow_test_path=allow_test_path)
    connect_args = {"check_same_thread": False}
    if url in _IN_MEMORY_URLS:
        return create_engine(url, echo=False, connect_args=connect_args, poolclass=StaticPool)
    return create_engine(url, echo=False, connect_args=connect_args)


# Colunas adicionadas ao Draft depois do primeiro release de demo (SSI-1006).
# ALTER TABLE idempotente preserva drafts e trilha de auditoria existentes; um draft
# aprovado legado fica com approved_revision NULL => o gate bloqueia o envio até
# reaprovação (o caminho seguro para aprovações anteriores ao vínculo por revisão).
_DRAFT_MIGRATIONS = {
    "revision": "INTEGER NOT NULL DEFAULT 1",
    "approved_revision": "INTEGER",
    "approved_state_sha256": "VARCHAR",
    "delivery_mode": "VARCHAR",
}


def _ensure_draft_columns(engine: Engine) -> None:
    """Adiciona colunas novas à tabela `draft` de DBs antigos (idempotente)."""
    with engine.connect() as conn:
        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(draft)")}
        for column, ddl in _DRAFT_MIGRATIONS.items():
            if column not in existing:
                conn.exec_driver_sql(f"ALTER TABLE draft ADD COLUMN {column} {ddl}")
        conn.commit()


def init_db(engine: Engine) -> None:
    """Create all tables if they don't exist, then apply in-place column migrations."""
    SQLModel.metadata.create_all(engine)
    _ensure_draft_columns(engine)
