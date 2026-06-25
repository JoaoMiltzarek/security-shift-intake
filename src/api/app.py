"""FastAPI application for the approval gate.

`create_app(engine, sender)` builds the app with injectable persistence and sender
so tests run against an in-memory DB and a mock sender. The module-level `app` is
the default instance for `uvicorn`.

Endpoints expose the state machine: submit -> review -> approve/reject -> send.
Sending always goes through the gate (M7.b) — never auto-sent.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.engine import Engine
from sqlmodel import Session

from src.api import repository
from src.api.db import init_db, make_engine
from src.api.gate import (
    DraftNotApprovedError,
    DraftNotReviewableError,
    MockSender,
    Sender,
    assert_reviewable,
    send_draft,
)
from src.api.models import Draft
from src.pipeline.draft import draft as draft_stage
from src.pipeline.validate import validate
from src.schema.config import ReportConfig
from src.schema.loader import load_config
from src.schema.state import ApprovalStatus, ExtractedField, PipelineState

_templates = Jinja2Templates(directory="ui/templates")
_DEFAULT_CONFIG = Path("configs/htmicron_security.yaml")


def _render(request: Request, template: str, context: dict[str, Any]) -> HTMLResponse:
    """Render a template to an HTMLResponse (typed boundary over TemplateResponse)."""
    response: HTMLResponse = _templates.TemplateResponse(request, template, context)
    return response


def _review_context(draft: Draft) -> dict[str, Any]:
    """Parse a draft's stored PipelineState into template-friendly pieces."""
    state = PipelineState.model_validate_json(draft.state_json)
    return {
        "draft": draft,
        "transcription": state.transcription,
        "fields": state.extracted_fields,
        "classification": state.classification,
        "recipients": state.recipients,
        "email_draft": state.email_draft,
    }


def _draft_summary(draft: Draft) -> dict[str, Any]:
    return {
        "id": draft.id,
        "status": draft.status,
        "created_at": draft.created_at.isoformat(),
        "updated_at": draft.updated_at.isoformat(),
        "sent_at": draft.sent_at.isoformat() if draft.sent_at else None,
    }


def create_app(
    engine: Engine | None = None,
    sender: Sender | None = None,
    config: ReportConfig | None = None,
) -> FastAPI:
    engine = engine or make_engine()
    init_db(engine)
    active_sender: Sender = sender or MockSender()
    active_config: ReportConfig = config or load_config(_DEFAULT_CONFIG)

    app = FastAPI(
        title="security-shift-intake",
        version="0.9.0",
        summary="Staged intake pipeline for handwritten security shift reports.",
    )

    def get_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/drafts", status_code=201)
    def submit(
        state: PipelineState, session: Session = Depends(get_session)
    ) -> dict[str, Any]:
        draft = repository.create_draft(session, state)
        return _draft_summary(draft)

    @app.get("/drafts")
    def list_drafts(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
        return [_draft_summary(d) for d in repository.list_drafts(session)]

    @app.get("/drafts/{draft_id}")
    def get_draft(draft_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
        draft = repository.get_draft(session, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
        summary = _draft_summary(draft)
        summary["state"] = json.loads(draft.state_json)
        summary["audit"] = [
            {"actor": a.actor, "action": a.action, "detail": a.detail,
             "timestamp": a.timestamp.isoformat()}
            for a in repository.get_audit(session, draft_id)
        ]
        return summary

    @app.post("/drafts/{draft_id}/approve")
    def approve(
        draft_id: int, actor: str = "reviewer", session: Session = Depends(get_session)
    ) -> dict[str, Any]:
        draft = repository.get_draft(session, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
        state = PipelineState.model_validate_json(draft.state_json)
        try:
            assert_reviewable(state)  # plano R4: block approval with pending fields
        except DraftNotReviewableError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _set_status(session, draft_id, ApprovalStatus.APPROVED, actor)

    @app.post("/drafts/{draft_id}/reject")
    def reject(
        draft_id: int, actor: str = "reviewer", session: Session = Depends(get_session)
    ) -> dict[str, Any]:
        return _set_status(session, draft_id, ApprovalStatus.REJECTED, actor)

    @app.post("/drafts/{draft_id}/send")
    def send(
        draft_id: int, actor: str = "reviewer", session: Session = Depends(get_session)
    ) -> dict[str, Any]:
        try:
            draft = send_draft(session, draft_id, active_sender, actor=actor)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DraftNotApprovedError as exc:
            # 409 Conflict: the draft's state forbids sending.
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _draft_summary(draft)

    def _set_status(
        session: Session, draft_id: int, status: ApprovalStatus, actor: str
    ) -> dict[str, Any]:
        try:
            draft = repository.set_status(session, draft_id, status, actor)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _draft_summary(draft)

    # ----- HTMX review UI -----

    def _require_draft(session: Session, draft_id: int) -> Draft:
        draft = repository.get_draft(session, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
        return draft

    def _status_panel(
        request: Request, draft: Draft, session: Session, message: str | None = None
    ) -> HTMLResponse:
        return _render(
            request,
            "_status_panel.html",
            {"draft": draft, "audit": repository.get_audit(session, draft.id or 0),
             "message": message},
        )

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
        return _render(request, "list.html", {"drafts": repository.list_drafts(session)})

    @app.get("/drafts/{draft_id}/review", response_class=HTMLResponse)
    def review(
        request: Request, draft_id: int, session: Session = Depends(get_session)
    ) -> HTMLResponse:
        draft = _require_draft(session, draft_id)
        ctx: dict[str, Any] = {"draft": draft, "audit": repository.get_audit(session, draft_id)}
        ctx.update(_review_context(draft))
        return _render(request, "review.html", ctx)

    @app.post("/ui/drafts/{draft_id}/approve", response_class=HTMLResponse)
    def ui_approve(
        request: Request, draft_id: int, session: Session = Depends(get_session)
    ) -> HTMLResponse:
        draft = _require_draft(session, draft_id)
        state = PipelineState.model_validate_json(draft.state_json)
        try:
            assert_reviewable(state)  # plano R4: block approval with pending fields
        except DraftNotReviewableError as exc:
            return _status_panel(request, draft, session, message=f"Blocked: {exc}")
        draft = repository.set_status(session, draft_id, ApprovalStatus.APPROVED, "reviewer")
        return _status_panel(request, draft, session)

    @app.post("/ui/drafts/{draft_id}/reject", response_class=HTMLResponse)
    def ui_reject(
        request: Request, draft_id: int, session: Session = Depends(get_session)
    ) -> HTMLResponse:
        draft = repository.set_status(session, draft_id, ApprovalStatus.REJECTED, "reviewer")
        return _status_panel(request, draft, session)

    @app.post("/ui/drafts/{draft_id}/send", response_class=HTMLResponse)
    def ui_send(
        request: Request, draft_id: int, session: Session = Depends(get_session)
    ) -> HTMLResponse:
        try:
            draft = send_draft(session, draft_id, active_sender, actor="reviewer")
            return _status_panel(request, draft, session, message="Sent.")
        except DraftNotApprovedError as exc:
            draft = _require_draft(session, draft_id)
            return _status_panel(request, draft, session, message=f"Blocked: {exc}")

    @app.post("/ui/drafts/{draft_id}/edit", response_class=HTMLResponse)
    async def ui_edit(
        request: Request, draft_id: int, session: Session = Depends(get_session)
    ) -> HTMLResponse:
        draft = _require_draft(session, draft_id)
        form = await request.form()
        state = PipelineState.model_validate_json(draft.state_json)

        # Human-confirmed values get full confidence (no longer "guessed" OCR);
        # the critic still flags any that are type-invalid or required-but-blank.
        new_fields: list[ExtractedField] = []
        for field in active_config.fields:
            raw = form.get(f"field__{field.name}")
            value = raw.strip() if isinstance(raw, str) and raw.strip() else None
            new_fields.append(
                ExtractedField(name=field.name, value=value, confidence=1.0 if value else 0.0)
            )

        state = state.model_copy(update={"extracted_fields": new_fields})
        state = validate(state, active_config)   # recompute MUST_REVIEW flags
        state = draft_stage(state, active_config)  # re-render the email draft
        repository.update_state(session, draft_id, state, actor="reviewer", action="edited")

        updated = _require_draft(session, draft_id)
        ctx: dict[str, Any] = {"audit": repository.get_audit(session, draft_id)}
        ctx.update(_review_context(updated))
        return _render(request, "_review_body.html", ctx)

    return app


app = create_app()
