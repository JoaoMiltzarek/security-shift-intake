"""Persistence models for the approval gate (SQLModel / SQLite).

A `Draft` is a submitted report awaiting human review; its `status` is the
authoritative state for the send gate. Every state change is recorded as an
immutable `AuditEntry` (who / what / when) — required by the human-approval-gate
invariant.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel

from src.schema.state import ApprovalStatus


def utcnow() -> datetime:
    return datetime.now(UTC)


class Draft(SQLModel, table=True):
    """A report draft persisted for review. `status` drives the send gate."""

    id: int | None = Field(default=None, primary_key=True)
    # Stored as the enum's string value ("pending"/"approved"/"rejected").
    status: str = Field(default=ApprovalStatus.PENDING)
    # Full PipelineState serialized as JSON (transcription, fields, classification,
    # recipients, draft, ...). The review screen reconstructs it from here.
    state_json: str
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    sent_at: datetime | None = Field(default=None)


class AuditEntry(SQLModel, table=True):
    """An immutable audit-log row: who did what to which draft, and when."""

    id: int | None = Field(default=None, primary_key=True)
    draft_id: int = Field(foreign_key="draft.id", index=True)
    actor: str
    action: str
    detail: str | None = Field(default=None)
    timestamp: datetime = Field(default_factory=utcnow)
