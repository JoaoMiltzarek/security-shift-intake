"""Database engine and session helpers for the approval-gate API.

Importing this module registers the SQLModel tables (via `models`). Tests use an
in-memory SQLite engine; the app uses a file-backed one.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

# Importing models registers the tables on SQLModel.metadata before create_all.
from src.api import models  # noqa: F401  (side-effect import)

DEFAULT_DB_URL = "sqlite:///data/app.db"


def make_engine(url: str = DEFAULT_DB_URL) -> Engine:
    """Create an engine. check_same_thread=False lets FastAPI use it across threads."""
    return create_engine(url, echo=False, connect_args={"check_same_thread": False})


def init_db(engine: Engine) -> None:
    """Create all tables if they don't exist."""
    SQLModel.metadata.create_all(engine)


def session_factory(engine: Engine) -> Iterator[Session]:
    """Yield a session bound to *engine* (FastAPI dependency / context use)."""
    with Session(engine) as session:
        yield session
