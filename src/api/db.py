"""Database engine and session helpers for the approval-gate API.

Importing this module registers the SQLModel tables (via `models`). Tests use an
in-memory SQLite engine; the app uses a file-backed one.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

# Importing models registers the tables on SQLModel.metadata before create_all.
from src.api import models  # noqa: F401  (side-effect import)

# Drafts contain PII (transcription/fields), so the DB lives in the gitignored
# `private/` folder by default. Override with INTAKE_DB_URL.
DEFAULT_DB_URL = os.environ.get("INTAKE_DB_URL", "sqlite:///private/app.db")
_IN_MEMORY_URLS = {"sqlite://", "sqlite:///:memory:"}


def _ensure_parent_dir(url: str) -> None:
    """Create the parent folder for a file-backed sqlite URL (e.g. private/)."""
    prefix = "sqlite:///"
    if url.startswith(prefix) and url not in _IN_MEMORY_URLS:
        Path(url[len(prefix):]).expanduser().resolve().parent.mkdir(
            parents=True, exist_ok=True
        )


def make_engine(url: str = DEFAULT_DB_URL) -> Engine:
    """Create an engine. check_same_thread=False lets FastAPI use it across threads.

    For in-memory SQLite, use a StaticPool so every session shares the one
    connection (otherwise each session gets a fresh, empty database).
    """
    connect_args = {"check_same_thread": False}
    if url in _IN_MEMORY_URLS:
        return create_engine(
            url, echo=False, connect_args=connect_args, poolclass=StaticPool
        )
    _ensure_parent_dir(url)
    return create_engine(url, echo=False, connect_args=connect_args)


def init_db(engine: Engine) -> None:
    """Create all tables if they don't exist."""
    SQLModel.metadata.create_all(engine)
