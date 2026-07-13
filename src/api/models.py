"""Persistence models for the approval gate (SQLModel / SQLite).

A `Draft` is a submitted report awaiting human review; its `status` is the
authoritative state for the send gate. Every state change is recorded as an
append-only `AuditEntry` (who / what / when) plus a `DraftRevision` content
snapshot — required by the human-approval-gate invariant.
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
    # Vínculo aprovação↔conteúdo (SSI-1006): toda edição incrementa `revision`; aprovar
    # estampa `approved_revision` + sha256 do state_json aprovado. O gate de envio exige
    # revisão E hash iguais — uma aprovação nunca vale para conteúdo que o revisor não viu.
    revision: int = Field(default=1)
    approved_revision: int | None = Field(default=None)
    approved_state_sha256: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    sent_at: datetime | None = Field(default=None)


class AuditEntry(SQLModel, table=True):
    """An audit-log row: who did what to which draft, and when.

    Append-only PELA APLICAÇÃO (nenhum caminho de código atualiza/apaga linhas) —
    não é imutabilidade criptográfica; a prova de conteúdo vem do `DraftRevision`
    (snapshot + sha256 por revisão) referenciado pelos details `rev=N sha256=...`.
    """

    id: int | None = Field(default=None, primary_key=True)
    draft_id: int = Field(foreign_key="draft.id", index=True)
    actor: str
    action: str
    detail: str | None = Field(default=None)
    timestamp: datetime = Field(default_factory=utcnow)


class DraftRevision(SQLModel, table=True):
    """Snapshot de UMA revisão do conteúdo de um draft (SSI-1008).

    Gravado em toda criação/edição; nunca sobrescrito. Permite provar exatamente
    qual conteúdo cada aprovação/envio referenciou (via `approved_state_sha256`).
    Contém PII como o próprio draft — vive no mesmo DB gitignorado em private/.
    """

    id: int | None = Field(default=None, primary_key=True)
    draft_id: int = Field(foreign_key="draft.id", index=True)
    revision: int
    state_sha256: str
    state_json: str
    created_at: datetime = Field(default_factory=utcnow)
